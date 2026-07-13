# `SelfSustaining`: ContextVar-backed storage

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
from contextvars import ContextVar, Token
from typing import Self


class SelfSustainingMeta(type):
    def __new__(mcls, name, bases, ns):
        ns["_self"] = ContextVar(f"{name}.instance", default=None)
        return super().__new__(mcls, name, bases, ns)

    @property
    def self(cls):
        if (instance := cls._self.get()) is None:
            raise AttributeError(f"{cls.__name__} is not bound")
        return instance

    def __getattr__(cls, name):
        return getattr(cls.self, name)

    def __setattr__(cls, name, value):
        if (instance := cls._self.get()) is None:
            return super().__setattr__(name, value)
        return setattr(instance, name, value)


class SelfSustaining(metaclass=SelfSustainingMeta):
    def __init__(self, *args, **kwargs) -> None:
        type(self).bind(self)

    @classmethod
    def bind(cls, instance: Self | None) -> Token[Self | None]:
        return cls._self.set(instance)

    @classmethod
    def reset(cls, token: Token[Self | None]) -> None:
        cls._self.reset(token)
```

`Configs.general`, `TC.general.X`, `TC.from_[TokenHeaderSource]` — unchanged syntax. The only thing that moved is what backs `cls._self.get()`.

`__setattr__` is keyed off *whether an instance is bound yet*, not a name allowlist: before construction, behave like a plain class-attribute set; once bound, forward everything to the instance. This covers `__parameters__` — Python's own `typing._generic_init_subclass` does `cls.__parameters__ = tuple(tvars)` as the first write to that name, before construction, before it's in `__dict__` — without naming it explicitly. Verified: removing the "is bound" branch entirely and watching `class Foo[T](SelfSustaining): pass` crash immediately confirms this is load-bearing, not defensive cruft.

`bind`/`reset` are the public pair for swapping the bound instance — added after noticing that `tc_context`, `override_fields`, and several test files were all reaching into `_self` (a leading-underscore, meant-to-be-internal attribute) directly from *outside* the class. Checked for name collisions against `Configs`/`RabbitSubscriber`/`KafkaSubscriber`/`RedisHandler`'s own methods first (none — `Configs.set`/`Configs.reset` don't exist; `Configs.set(tenant, value)` is a different, existing method with a different arity). `SelfSustaining.__init__` itself now calls `type(self).bind(self)` rather than touching `_self` directly, for the same consistency. `.self` stays a read-only property (see the naming-collision discussion in "Eager values" below) — it has no setter, so binding/resetting always goes through `bind`/`reset`, never `Cls.self = ...`. The one legitimate remaining direct `_self` access outside `meta.py` is `Configs.__init__`'s idempotency guard (`type(self)._self.get() is not None`), which needs the *non-raising* check — `.self` raising on unbound is the wrong behavior for "is this the first construction or not."

No shared `override()`/swap-safely context manager on the base class. Checked every production construction site (`main.py`'s `Configs(...)`/`RabbitSubscriber(...)`/`KafkaSubscriber(...)`/`RedisHandler(...)` calls) and found zero callers that swap or reset an already-bound instance — that only happens in tests. Also considered whether Vault-based secret rotation (a planned future feature) might be a genuine runtime caller: it isn't, because rotation wants a *permanent* rebind, and `.override()`'s whole shape is a context manager that reverts on exit — the wrong tool even if rotation existed today. So the set/try/finally/reset pattern is inlined directly into its one actual caller, `tc_context` (see below), using `bind`/`reset` rather than living as a context-manager method on the production base class for a need only tests have.

### Per-field override

`Configs.__init__` (`fastloom/tenant/settings.py:77-119`) doesn't just set `self.general` — it fans that value out, once, into `from_`/`settings_from` (captured by value into a closure), `auth`/`optional_auth` (`JWTAuth(self.general)`), and two cross-class mutations: `BaseDocumentSignal._PROJECT_NAME` and `BaseCache.Meta` (via `rewrite_cache_meta`, which has the identical fan-out-once shape). A cheap "just swap `.general`" override would leave all of that stale.

So: per-field override is a *data-only* patch, valid only for fields nothing else derives from:

```python
    @classmethod
    @contextmanager
    def override_fields(cls, **field_updates):
        patched = copy.copy(cls.self)  # reuses existing Mongo/Redis/tenant machinery
        patched.general = patched.general.model_copy(update=field_updates)
        token = cls.bind(patched)
        try:
            yield patched
        finally:
            cls.reset(token)
```

Documented caveat, not hidden: overriding `PROJECT_NAME` itself (or anything else `_setup_mongo`/`_setup_redis` derived from) via `override_fields` leaves `BaseDocumentSignal._PROJECT_NAME`/cache key prefixes pointing at the old value. Reconstruct fully (`Configs(service_cls, tenant_cls)`, re-running `__init__`) whenever the overridden field feeds a derived side effect; use `override_fields(...)` for independent flags.

### Test fixtures: `tc_context` inlines the set/reset pattern directly, scope left unchanged

Implemented: `tc_context`/`TC`/`settings_mock` in `fastloom/test/fixtures/settings.py` now do `token = Configs.bind(Configs(...)); try: yield Configs.self; finally: Configs.reset(token)` — using the public `bind`/`reset` pair rather than reaching into `_self` directly, and instead of manual `Configs.self = None` before/after. Same external behavior, correct token-based reset.

**Deliberately not changed**: the shipped `TC` fixture's scope stays function-scoped (unchanged from today), rather than flipping the default to `session, autouse=True` as originally proposed. Reason found during implementation: if `TC` becomes session-scoped by default while a consuming service's own `service_settings`/`tenant_settings` fixtures stay function-scoped (pytest's normal default, and not verified for every fastloom consumer — only `iam` and `assistant` were audited), pytest raises a hard `ScopeMismatch` error at collection time for that service's entire suite, not a subtle behavior change. `iam` and `assistant` already get session-scoped behavior today by overriding the fixture themselves at their own conftest — that pattern still works unchanged and is the recommended path until every consumer's fixture scopes are confirmed. Both `iam`'s and `assistant`'s existing overrides can keep using `tc_context` as-is, or call `Configs.bind(...)`/`Configs.reset(...)` directly, but that's a per-service follow-up, not part of this change.

A per-test/per-case override (feature-flag testing) is then just:

```python
def test_feature_x():
    with Configs.override_fields(FEATURE_X=True):
        ...
    # session config restored here, automatically
```

### Eager values (topic names, `Depends(...)`) — no new mechanism needed

`iam`'s production code already does `Depends(TC.auth.get_claims)` as an eager function-default, evaluated once at import time, and it already works — because `main.py`'s `app()` factory constructs `Configs`/brokers *before* `get_app()` imports any route/signal module (`fastloom/launcher/main.py:52-58`). This is the same principle that makes `iam`'s `constants.py` `StrEnum` topics safe. The fix for "I hate lazy functions in API dependencies" isn't a new mechanism — it's documenting and relying on the same construction-before-import discipline everywhere, which this design doesn't change (`SelfSustaining`'s job is unaffected by *when* `Cls(...)` is called, only by *what* backs the binding once it is).

The one place discipline is still required, unrelated to `ContextVar` vs. class-attribute: a value needed at *test-collection* time (an eager class-body constant in a test file) still requires the binding to happen at conftest **module** scope, not inside a fixture (autouse or not) — pytest imports conftest.py before collecting sibling test files, but fixtures only run after the entire collection phase. `patch_tenant_loader_at_import` (already shipped, PR #17) remains the mechanism for that specific case.

## Verified non-issues (audited, not assumed)

- **FastStream context propagation**: every task-spawning hop in the Kafka consumer path (`broker.start()` → `subscriber.start()` → `add_task(self._consume)` → per-message dispatch, including the `ConcurrentDefaultSubscriber`'s extra `anyio.TaskGroup.start_soon` hop) uses either a plain `await` in the same task or `asyncio.create_task`/`loop.create_task` with no explicit `context=` override — Python's default (copy the caller's context) applies throughout. A binding made before `broker.start()` reliably reaches every handler invocation.
- **Background tasks** (`assistant/core/db/lifespan.py`'s `tick_task`/`sync_task`/`curve_metrics_task`/`pnl_sweep_task`) are all created inside the lifespan context that already has `Configs` bound — inherit correctly via `asyncio.create_task`'s default context-copy.
- **Per-tenant settings caching** (`BaseTenantSettingCache`, `HostTenantMapping`, `SettingCacheSchema`) isn't built on `SelfSustaining` at all — `Configs.get(tenant)`/`await TC[tenant]` is a method call on whichever instance the `ContextVar` currently holds, so it just works. (`SettingCacheSchema`'s dynamically-`create_model()`'d classes already get rebuilt on every full `Configs` reconstruction today, via the existing reset-dance — no new cost introduced.)
- **Vault-sourced settings** (future plan: fetch `KAFKA_URI`/`RABBIT_URI`/`MONGO_URI`/`POSTGRES_DSN`-style fields from Vault before constructing `Settings`): compatible without touching this design. `load_settings(settings_cls, config_stream=...)` already accepts a flexible `config_stream`; Vault-fetched values merge into whatever produces that stream *before* `Configs(...)` is called. The one mechanical question is that Vault I/O is async while `Configs.__init__` is sync — resolve by doing the Vault fetch in a separate `async` pre-step and making `main.py`'s `app()` factory `async def` (uvicorn supports async factories with `factory=True`), not by making `Configs.__init__` itself async. Tests are unaffected either way — they already synthesize YAML directly and never touch Vault or a real `tenants.yaml`.
- **Multi-process safety** (`iam` runs `WORKERS: 4`, `assistant` similarly multi-worker): `ContextVar`s don't cross process boundaries, and neither does today's class attribute — no behavior change, confirmed via `fastloom/launcher/main.py` (each uvicorn worker is a separate OS process, each independently importing/constructing `Configs` once).

## Migration (audited, bounded)

`.self` came back, narrower than before: a read-only property (`SelfSustainingMeta.self`, no setter) that raises `AttributeError` if unbound, used only where "the currently bound instance" is needed as an object in its own right (see the `resolve`/naming-collision discussion above) rather than a forwarded field. Full list:

- `fastloom/meta.py` — the metaclass itself (expected; this *is* the change).
- `fastloom/tenant/settings.py:82` — idempotency guard, instance-level: `if self.self is not None` → `if type(self)._self.get() is not None` (deliberately *not* `.self` — this needs the non-raising check for the normal first-construction case).
- `fastloom/tenant/settings.py:61` (`GetSettingsFrom._item_getter`) and `fastloom/tenant/handler.py:34` (`get_tenant_settings`) — **no change needed relative to the original code**, since `.self` is back with the same read shape: `Configs.self.get(tenant)` / `configs.self[tenant]`, just minus the pointless `[BaseModel, V]` generic subscript (confirmed via mypy that it was never doing anything — the line type-checks identically without it).
- `fastloom/test/fixtures/settings.py` (`tc_context`) — still does the set/try/finally/reset inline via `._self` directly, since that's a *write* (bind a fresh instance, later revert) — `.self` has no setter, deliberately, so this doesn't go through it.
- 4 fastloom test files (`test_launcher_depends.py`, `test_key_prefixes.py`, `test_lifehooks.py`, `kafka/conftest.py`) construct via `Cls.__new__(Cls)` + direct `.self = ...`/`.self = None` — these are *writes*, so rewritten to `Cls.bind(...)`/`Cls.bind(None)` (the public pair, not `._self.set(...)` directly).
- `iam` production code: **nothing required** — confirmed via audit, no direct `.self` access anywhere outside its own test fixtures.
- **`assistant`, split by read vs. write**: `alembic/env.py:67-68` (`TC.self.general.POSTGRES_DSN`) is a *read* — **no change needed**, works unchanged against the restored property. Their documented `PGManager.self = None`/`CHManager.self = None` test-reset convention (`.claude/docs/conventions.md`, `tests/fixtures/postgres.py`, `tests/fixtures/redis.py`) is a *write* — `.self` has no setter, so these need `PGManager.bind(None)` / `CHManager.bind(None)`.

**Confirmed, not just assumed**: fastloom's own 80 tests pass with all of the above applied — ruff/mypy/pre-commit clean.

## Non-goals

- Not eliminating `from settings import TC` — that needs a custom mypy plugin to do without losing static type safety, which is out of scope (flagged as Approach B in discussion, explicitly not pursued here).
- Not making `Configs.__init__` async — Vault integration is handled as a pre-construction step instead.
- Not touching `RabbitSubscriber`/`KafkaSubscriber`/`RedisHandler`'s own internals beyond inheriting the new `SelfSustaining` — same `ContextVar`-backed storage applies to them automatically.
- Not adding a shared `override()`/swap-safely method to the base class — audited every production construction site and found zero callers; it would be a test-only concept living in the production class, so the pattern is inlined into its one real caller (`tc_context`) instead.
- Not flipping the shipped `TC` fixture's default scope to session — see the fixtures section above for why.

## Resolved during implementation

1. `override_fields` lives on `Configs` specifically (`fastloom/tenant/settings.py`), not on `SelfSustaining` generically — `RabbitSubscriber`/`KafkaSubscriber`/`RedisHandler` have no equivalent "one field" concept, and adding an unused generic method to all four would be exactly the kind of premature abstraction this codebase's own conventions warn against.
2. The YAML dump-then-reparse round trip in `tc_context`/`patched_settings` was left as-is — collapsing it into a direct "construct from pre-built instances" path is a separate, unrelated simplification and would have widened this diff beyond the actual goal.

## Implementation

Shipped in this PR: `fastloom/meta.py` (`SelfSustainingMeta`/`SelfSustaining` rewrite — `_self` ContextVar, `__setattr__` keyed off bound-or-not rather than a name allowlist, `.self` restored as a narrow read-only raise-on-unbound property, public `bind`/`reset` classmethod pair, no shared `override()`), `fastloom/tenant/settings.py` (idempotency-guard fix + `override_fields` using `bind`/`reset`, `GetSettingsFrom._item_getter` unchanged in shape from the original code), `fastloom/tenant/handler.py` (unchanged in shape from the original code), `fastloom/test/fixtures/settings.py` (`tc_context` uses `bind`/`reset`), and 4 fastloom test files updated to `Cls.bind(...)`. All 80 existing tests pass; ruff/mypy/pre-commit clean.
