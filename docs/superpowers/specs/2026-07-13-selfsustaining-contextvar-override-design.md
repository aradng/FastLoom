# `SelfSustaining`: ContextVar-backed storage + a shared `.override()`

## Problem

`SelfSustaining` (`fastloom/meta.py`) backs `Configs`, `RabbitSubscriber`, `KafkaSubscriber`, `RedisHandler`. Today it stores the bound instance as a plain mutable class attribute (`cls.self`), forwarded via metaclass `__getattr__`/`__setattr__`. Swapping settings for a test is a manual, per-call-site dance: `Cls.self = None` → rebuild → `Cls.self = None` again, in a `try/finally`. Every service that needs this re-derives it independently — `iam` and `assistant` each hand-wrote a nearly identical session-scoped `TC` fixture; `iam` additionally hand-wrote a conftest-module-scope loader monkeypatch to make an eager `TC = Configs(...)` binding safe under pytest collection. None of this is shared; all of it is tribal knowledge re-invented per service.

Separately: services want to write eager values (topic `StrEnum`s, `Depends(TC.auth.get_claims)`) instead of wrapper functions, and feature-flag-style testing (swapping one field between test cases, not the whole settings object) is coming and needs to not be ceremony.

## Constraints (given)

- Type safety first — no loss of static narrowing on `Configs.general.X`.
- No singleton that can't be overridden — the actual pain is the reset-dance ceremony, not concurrent-context isolation (confirmed).
- Feature-flag-style per-test settings variation must stay first-class, not become a rare escape hatch (confirmed — not yet exercised in practice only because prior fastloom-based projects haven't needed it yet, not because it's unneeded).
- Minimal code; no custom mypy plugin (that's the only way to also drop `from settings import TC` entirely, and it's out of scope here).
- Don't want to write lazy/wrapper functions in API dependencies or similar just to defer a read.

## Design

### Storage: `ContextVar` instead of a raw class attribute

```python
from contextvars import ContextVar
from contextlib import contextmanager
from typing import Self


class SelfSustainingMeta(type):
    def __new__(mcls, name, bases, ns):
        ns["_var"] = ContextVar(f"{name}.instance", default=None)
        return super().__new__(mcls, name, bases, ns)

    def __getattr__(cls, name):
        instance = cls._var.get()
        if instance is None:
            raise AttributeError(f"{cls.__name__} not bound in this context")
        return getattr(instance, name)

    def __setattr__(cls, name, value):
        if name == "_var":
            return super().__setattr__(name, value)
        return setattr(cls._var.get(), name, value)

    @property
    def self(cls):
        """Back-compat alias for `cls._var.get()` — see Migration below."""
        return cls._var.get()

    @self.setter
    def self(cls, value):
        cls._var.set(value)


class SelfSustaining(metaclass=SelfSustainingMeta):
    def __init__(self, *args, **kwargs) -> None:
        type(self)._var.set(self)

    @classmethod
    @contextmanager
    def override(cls, *args, **kwargs):
        """Bind a fresh instance for the `with` block only. Whatever was
        bound before — prod singleton, an outer override, or nothing —
        comes back on exit. Nests correctly, unlike `Cls.self = None`."""
        token = cls._var.set(cls(*args, **kwargs))
        try:
            yield cls._var.get()
        finally:
            cls._var.reset(token)
```

`Configs.general`, `TC.general.X`, `TC.from_[TokenHeaderSource]` — unchanged syntax. The only thing that moved is what backs `cls._var.get()`.

### Per-field override

`Configs.__init__` (`fastloom/tenant/settings.py:77-119`) doesn't just set `self.general` — it fans that value out, once, into `from_`/`settings_from` (captured by value into a closure), `auth`/`optional_auth` (`JWTAuth(self.general)`), and two cross-class mutations: `BaseDocumentSignal._PROJECT_NAME` and `BaseCache.Meta` (via `rewrite_cache_meta`, which has the identical fan-out-once shape). A cheap "just swap `.general`" override would leave all of that stale.

So: per-field override is a *data-only* patch, valid only for fields nothing else derives from:

```python
    @classmethod
    @contextmanager
    def override_fields(cls, **field_updates):
        import copy
        current = cls._var.get()
        patched = copy.copy(current)  # reuses existing Mongo/Redis/tenant machinery
        patched.general = current.general.model_copy(update=field_updates)
        token = cls._var.set(patched)
        try:
            yield patched
        finally:
            cls._var.reset(token)
```

Documented caveat, not hidden: overriding `PROJECT_NAME` itself (or anything else `_setup_mongo`/`_setup_redis` derived from) via `override_fields` leaves `BaseDocumentSignal._PROJECT_NAME`/cache key prefixes pointing at the old value. Use full `override(...)` (which re-runs `__init__`) whenever the overridden field feeds a derived side effect; use `override_fields(...)` for independent flags.

### Test fixtures: session scope becomes the shipped default

Both `iam` and `assistant` already override fastloom's default (function-scoped, per-test rebuild) `TC` fixture to `scope="session", autouse=True`. Ship that as the default:

```python
# fastloom/test/fixtures/settings.py
@pytest.fixture(scope="session", autouse=True)
def TC(service_settings, tenant_settings):
    with Configs.override(service_settings, tenant_settings):
        yield Configs
```

A per-test/per-case override (feature-flag testing) is then just:

```python
def test_feature_x():
    with Configs.override_fields(FEATURE_X=True):
        ...
    # session config restored here, automatically
```

### Eager values (topic names, `Depends(...)`) — no new mechanism needed

`iam`'s production code already does `Depends(TC.auth.get_claims)` as an eager function-default, evaluated once at import time, and it already works — because `main.py`'s `app()` factory constructs `Configs`/brokers *before* `get_app()` imports any route/signal module (`fastloom/launcher/main.py:52-58`). This is the same principle that makes `iam`'s `constants.py` `StrEnum` topics safe. The fix for "I hate lazy functions in API dependencies" isn't a new mechanism — it's documenting and relying on the same construction-before-import discipline everywhere, which this design doesn't change (`SelfSustaining`'s job is unaffected by *when* `Cls(...)`/`.override()` is called, only by *what* backs the binding once it is).

The one place discipline is still required, unrelated to `ContextVar` vs. class-attribute: a value needed at *test-collection* time (an eager class-body constant in a test file) still requires the binding to happen at conftest **module** scope, not inside a fixture (autouse or not) — pytest imports conftest.py before collecting sibling test files, but fixtures only run after the entire collection phase. `patch_tenant_loader_at_import` (already shipped, PR #17) remains the mechanism for that specific case.

## Verified non-issues (audited, not assumed)

- **FastStream context propagation**: every task-spawning hop in the Kafka consumer path (`broker.start()` → `subscriber.start()` → `add_task(self._consume)` → per-message dispatch, including the `ConcurrentDefaultSubscriber`'s extra `anyio.TaskGroup.start_soon` hop) uses either a plain `await` in the same task or `asyncio.create_task`/`loop.create_task` with no explicit `context=` override — Python's default (copy the caller's context) applies throughout. A binding made before `broker.start()` reliably reaches every handler invocation.
- **Background tasks** (`assistant/core/db/lifespan.py`'s `tick_task`/`sync_task`/`curve_metrics_task`/`pnl_sweep_task`) are all created inside the lifespan context that already has `Configs` bound — inherit correctly via `asyncio.create_task`'s default context-copy.
- **Per-tenant settings caching** (`BaseTenantSettingCache`, `HostTenantMapping`, `SettingCacheSchema`) isn't built on `SelfSustaining` at all — `Configs.get(tenant)`/`await TC[tenant]` is a method call on whichever instance the `ContextVar` currently holds, so it just works. (`SettingCacheSchema`'s dynamically-`create_model()`'d classes already get rebuilt on every full `Configs` reconstruction today, via the existing reset-dance — no new cost introduced.)
- **Vault-sourced settings** (future plan: fetch `KAFKA_URI`/`RABBIT_URI`/`MONGO_URI`/`POSTGRES_DSN`-style fields from Vault before constructing `Settings`): compatible without touching this design. `load_settings(settings_cls, config_stream=...)` already accepts a flexible `config_stream`; Vault-fetched values merge into whatever produces that stream *before* `Configs(...)` is called. The one mechanical question is that Vault I/O is async while `Configs.__init__` is sync — resolve by doing the Vault fetch in a separate `async` pre-step and making `main.py`'s `app()` factory `async def` (uvicorn supports async factories with `factory=True`), not by making `Configs.__init__` itself async. Tests are unaffected either way — they already synthesize YAML directly and never touch Vault or a real `tenants.yaml`.
- **Multi-process safety** (`iam` runs `WORKERS: 4`, `assistant` similarly multi-worker): `ContextVar`s don't cross process boundaries, and neither does today's class attribute — no behavior change, confirmed via `fastloom/launcher/main.py` (each uvicorn worker is a separate OS process, each independently importing/constructing `Configs` once).

## Migration (audited, bounded)

The `.self` back-compat property (metaclass-level) covers **class-level** access unchanged: `Configs.self`, `TC.self.general.X`, `Configs.self = None`. It does **not** cover instance-level access (`self.self` from inside a method), which needs a small explicit rewrite. Full list:

- `fastloom/meta.py` — the metaclass itself (expected; this *is* the change).
- `fastloom/tenant/settings.py:82` — idempotency guard `if self.self is not None: return` is instance-level, not covered by the class-level compat property. Rewrite to `if type(self)._var.get(None) is not None: return`.
- `fastloom/tenant/settings.py:60`, `fastloom/tenant/handler.py:34` — class-level `.self` access; covered by the compat property, but worth migrating to `.override()`/`._var.get()` directly as the new codebase eventually drops the shim.
- `fastloom/test/fixtures/settings.py:51,55` (`tc_context`) — rewrite to use `.override()` internally; external fixture behavior/name unchanged.
- 5 fastloom test files (`test_launcher_depends.py`, `test_key_prefixes.py`, `test_lifehooks.py`, `kafka/conftest.py`) construct via `Cls.__new__(Cls)` + direct `.self =` assignment, bypassing `__init__` — covered by the compat property short-term, should migrate to `.override()` to get correct nesting/reset behavior.
- `assistant/alembic/env.py:67-68` (`TC.self.general.POSTGRES_DSN`) — class-level, covered by compat property, no forced change.
- `assistant/sandbox/bench_curve_batch.py`, `tests/fixtures/postgres.py`, `tests/fixtures/redis.py` — same `.self =` idiom (including on `assistant`'s own `PGManager`, if it independently follows the same naming convention) — covered by compat property where genuinely class-level.
- `iam` production code: **nothing required** — no direct `.self` access anywhere outside its own test fixtures.

Net: the back-compat `.self` property means this ships without a coordinated flag-day migration of every downstream consumer. Only `fastloom/tenant/settings.py:82` is a forced, immediate rewrite; everything else can migrate to `.override()` opportunistically.

## Non-goals

- Not eliminating `from settings import TC` — that needs a custom mypy plugin to do without losing static type safety, which is out of scope (flagged as Approach B in discussion, explicitly not pursued here).
- Not making `Configs.__init__` async — Vault integration is handled as a pre-construction step instead.
- Not touching `RabbitSubscriber`/`KafkaSubscriber`/`RedisHandler`'s own internals beyond inheriting the new `SelfSustaining` — they get `.override()` for free with no class-specific work.

## Open questions for implementation planning

1. Should `override_fields` live only on `Configs` (the only class where "one field" is a meaningful concept today), or on `SelfSustaining` generically? `RabbitSubscriber`/`KafkaSubscriber`/`RedisHandler` don't have an obvious "fields" concept the way `Configs.general` does.
2. Should the YAML dump-then-reparse round trip in `tc_context`/`patched_settings` (`dump_settings(...)` → patch loader → `Configs(get_settings_cls(), get_tenant_cls())` re-parses it) be collapsed into a direct "construct from pre-built instances" path now that we're touching this code anyway, or left as a separate follow-up?
