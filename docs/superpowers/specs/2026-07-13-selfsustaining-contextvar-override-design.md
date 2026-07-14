# `SelfSustaining`: ContextVar-backed storage

## Problem

`SelfSustaining` (`fastloom/meta.py`) backs `Configs`, `RabbitSubscriber`, `KafkaSubscriber`, `RedisHandler`. It stores the bound instance as a plain mutable class attribute (`cls.self`), forwarded via metaclass `__getattr__`/`__setattr__`. Swapping settings for a test is a manual, per-call-site dance: `Cls.self = None` → rebuild → `Cls.self = None` again, in a `try/finally`. Every service that needs this re-derives it independently — `iam` and `assistant` each hand-wrote a nearly identical session-scoped `TC` fixture; `iam` additionally hand-wrote a conftest-module-scope loader monkeypatch to make an eager `TC = Configs(...)` binding safe under pytest collection. None of this is shared; all of it is tribal knowledge re-invented per service.

Separately: services want to write eager values (topic `StrEnum`s, `Depends(TC.auth.get_claims)`) instead of wrapper functions, and feature-flag-style testing (swapping one field between test cases, not the whole settings object) is coming and needs to not be ceremony.

## Constraints

- Type safety first — no loss of static narrowing on `Configs.general.X`.
- No singleton that can't be overridden — the pain point is the reset-dance ceremony, not concurrent-context isolation.
- Feature-flag-style per-test settings variation stays first-class, not a rare escape hatch — not yet exercised in practice only because prior fastloom-based projects haven't needed it yet, not because it's unneeded.
- Minimal code; no custom mypy plugin (the only way to also drop `from settings import TC` entirely, out of scope here).
- No lazy/wrapper functions in API dependencies or similar just to defer a read.

## Design

### Storage

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
    def bind(cls, instance: Self) -> Token[Self | None]:
        return cls._self.set(instance)

    @classmethod
    def unbind(cls) -> Token[Self | None]:
        return cls._self.set(None)

    @classmethod
    def reset(cls, token: Token[Self | None]) -> None:
        cls._self.reset(token)
```

`Configs.general`, `TC.general.X`, `TC.from_[TokenHeaderSource]` — same syntax as always; what backs it is a `ContextVar`, not a raw mutable class attribute.

**`__new__`** creates one `ContextVar` per subclass, at class-definition time, stored directly in that class's own namespace. This has to happen per-subclass (not as a plain attribute on `SelfSustaining` itself, which would be inherited and shared) so `Configs`, `RabbitSubscriber`, `KafkaSubscriber`, and `RedisHandler` each get an independent binding — otherwise constructing one would make the others appear bound too. Landing it in the `namespace` dict (rather than via `setattr` after the class exists) means `_self` is already present in `cls.__dict__` before any `__setattr__` call can happen at all.

**`self`** is a read-only property, not a writable attribute: reading it returns the bound instance or raises `AttributeError` if nothing is bound; there is no setter, so binding/unbinding only ever happens through `bind`/`unbind`/`reset`. `__getattr__` delegates to it, so the raise-if-unbound check lives in exactly one place.

**`__setattr__`** is keyed off *whether an instance is bound yet*, not a name allowlist: before construction, behave like a plain class-attribute set; once bound, forward everything to the instance. This is what makes Python's own `typing._generic_init_subclass` work — it writes `cls.__parameters__ = tuple(tvars)` directly, as the first write to that name, while defining any PEP-695-generic `SelfSustaining` subclass (`Configs[T, V]`), before construction, before `_self` even applies. Without the "not yet bound" branch, defining such a class crashes immediately with `AttributeError: Foo is not bound`.

**`bind`/`unbind`/`reset`** are the public, only sanctioned way to change or clear the binding from outside `meta.py`. `bind` takes an actual instance (not `Self | None`) — clearing to unbound is `unbind()`, a distinct operation, not `bind(None)`. `reset(token)` restores whatever was bound before, correctly nested (an outer binding survives an inner one being reset). `SelfSustaining.__init__` itself goes through `bind`, not `_self` directly, so `_self` never needs to be touched from outside `meta.py` except in one place: `Configs.__init__`'s idempotency guard (`type(self)._self.get() is not None`), which needs the *non-raising* check — `.self` raising on unbound is the wrong behavior for "is this the first construction or not."

There is no shared `override()`/swap-safely context manager on the base class. Every production construction site (`main.py`'s `Configs(...)`/`RabbitSubscriber(...)`/`KafkaSubscriber(...)`/`RedisHandler(...)` calls) constructs once and never swaps or resets an already-bound instance — that only happens in tests, via `bind`/`reset` directly at the one real call site (`tc_context`, below). A hypothetical runtime rebind (e.g. Vault secret rotation) wouldn't use a context-manager shape anyway, since rotation wants a *permanent* rebind, not revert-on-exit.

### Per-field override — `fastloom.test.fixtures.settings.override_fields`

`Configs.__init__` (`fastloom/tenant/settings.py:77-119`) doesn't just set `self.general` — it fans that value out, once, into `from_`/`settings_from` (captured by value into a closure), `auth`/`optional_auth` (`JWTAuth(self.general)`), and two cross-class mutations: `BaseDocumentSignal._PROJECT_NAME` and `BaseCache.Meta` (via `rewrite_cache_meta`, same fan-out-once shape). A cheap "just swap `.general`" override leaves all of that stale.

So per-field override is a *data-only* patch, valid only for fields nothing else derives from, and lives as a plain function in test fixtures (not on `Configs`, since it has no production caller):

```python
@contextmanager
def override_fields(**field_updates: object):
    from fastloom.tenant.settings import Configs

    patched = copy.copy(Configs.self)  # reuses existing Mongo/Redis/tenant machinery
    patched.general = patched.general.model_copy(update=field_updates)
    token = Configs.bind(patched)
    try:
        yield patched
    finally:
        Configs.reset(token)
```

Documented caveat, not hidden: overriding `PROJECT_NAME` itself (or anything else `_setup_mongo`/`_setup_redis` derives from) via `override_fields` leaves `BaseDocumentSignal._PROJECT_NAME`/cache key prefixes pointing at the old value. Reconstruct fully (`tc_context`/`TC`, which re-runs `__init__`) whenever the overridden field feeds a derived side effect; use `override_fields(...)` for independent flags:

```python
from fastloom.test.fixtures.settings import override_fields

def test_feature_x():
    with override_fields(FEATURE_X=True):
        ...
    # prior config restored here, automatically
```

### Test fixtures

`tc_context`/`TC`/`settings_mock` in `fastloom/test/fixtures/settings.py`:

```python
with patched_settings(service_settings, tenant_settings):
    token = Configs.bind(Configs(get_settings_cls(), get_tenant_cls()))
    try:
        yield Configs.self
    finally:
        Configs.reset(token)
```

The shipped `TC` fixture stays function-scoped. `iam` and `assistant` each override it to `session, autouse=True` at their own conftest, since neither needs per-test settings variation today — that pattern is unaffected by this design and remains the way to opt into session scope. Flipping the shipped default to session-scoped isn't done here: if a consuming service's own `service_settings`/`tenant_settings` fixtures stay function-scoped (pytest's normal default) while `TC` is session-scoped, pytest raises `ScopeMismatch` at collection time for that service's entire suite — a real risk not worth taking without confirming every consumer's fixture scopes first.

### Eager values (topic names, `Depends(...)`)

`iam`'s production code does `Depends(TC.auth.get_claims)` as an eager function-default, evaluated once at import time, and it works — because `main.py`'s `app()` factory constructs `Configs`/brokers *before* `get_app()` imports any route/signal module (`fastloom/launcher/main.py:52-58`). Same principle that makes `iam`'s `constants.py` `StrEnum` topics safe: eager values are safe wherever construction demonstrably happens before anything imports the referencing module, which is a property of import/construction ordering, not of `ContextVar` vs. class-attribute — `SelfSustaining`'s job is unaffected by *when* `Cls(...)` is called, only by *what* backs the binding once it is.

One place discipline is still required regardless of storage mechanism: a value needed at *test-collection* time (an eager class-body constant in a test file) requires the binding to happen at conftest **module** scope, not inside a fixture (autouse or not) — pytest imports conftest.py before collecting sibling test files, but fixtures only run after the entire collection phase. `patch_tenant_loader_at_import` (`fastloom/test/fixtures/settings.py`, documented in `docs/test.md`) is the mechanism for that case.

## Verified compatibility

- **FastStream context propagation**: every task-spawning hop in the Kafka consumer path (`broker.start()` → `subscriber.start()` → `add_task(self._consume)` → per-message dispatch, including the `ConcurrentDefaultSubscriber`'s extra `anyio.TaskGroup.start_soon` hop) uses either a plain `await` in the same task or `asyncio.create_task`/`loop.create_task` with no explicit `context=` override — Python's default (copy the caller's context) applies throughout. A binding made before `broker.start()` reliably reaches every handler invocation.
- **Background tasks** (`assistant/core/db/lifespan.py`'s `tick_task`/`sync_task`/`curve_metrics_task`/`pnl_sweep_task`) are all created inside the lifespan context that already has `Configs` bound — inherit correctly via `asyncio.create_task`'s default context-copy.
- **Per-tenant settings caching** (`BaseTenantSettingCache`, `HostTenantMapping`, `SettingCacheSchema`) isn't built on `SelfSustaining` at all — `Configs.get(tenant)`/`await TC[tenant]` is a method call on whichever instance the `ContextVar` currently holds, so it just works. `SettingCacheSchema`'s dynamically-`create_model()`'d classes get rebuilt on every full `Configs` reconstruction, same cost as before.
- **Vault-sourced settings** (future: fetch `KAFKA_URI`/`RABBIT_URI`/`MONGO_URI`/`POSTGRES_DSN`-style fields from Vault before constructing `Settings`): compatible without touching this design. `load_settings(settings_cls, config_stream=...)` already accepts a flexible `config_stream`; Vault-fetched values merge into whatever produces that stream *before* `Configs(...)` is called. Vault I/O is async while `Configs.__init__` is sync — resolved by doing the Vault fetch in a separate `async` pre-step and making `main.py`'s `app()` factory `async def` (uvicorn supports async factories with `factory=True`), not by making `Configs.__init__` itself async. Tests are unaffected either way — they synthesize YAML directly and never touch Vault or a real `tenants.yaml`.
- **Multi-process safety** (`iam` runs `WORKERS: 4`, `assistant` similarly multi-worker): `ContextVar`s don't cross process boundaries — each uvicorn worker is a separate OS process, independently importing/constructing `Configs` once.

## Known limitation: raw thread pools

`ContextVar` bindings propagate automatically across `asyncio.create_task`/`TaskGroup` (default context-copy — see "FastStream context propagation" above) and across `asyncio.to_thread`/`anyio.to_thread.run_sync` (both explicitly `copy_context()` before handing work to the worker thread). They do **not** propagate into a thread started via `loop.run_in_executor(...)` or a raw `concurrent.futures.ThreadPoolExecutor.submit(...)`/`threading.Thread(...).start()` — those get a fresh top-level `Context`, with no memory of anything `.set()` in the calling thread.

This bit `assistant/utils/tracing.py`'s `CustomSampler`: faststream's confluent-kafka transport runs `poll`/`consume`/`close`/`produce`/`commit` through a dedicated single-worker `ThreadPoolExecutor` (`faststream/confluent/helpers/client.py`), and OpenTelemetry's confluent-kafka auto-instrumentation wraps all five with a span, invoked from inside that same thread. A custom sampler reading `TC.general.X` there hit an unbound `Configs` — see below for what that did before `__getattr__` was fixed. Ordinary consumer handlers were never at risk; they run as `asyncio.Task`s dispatched from the (context-propagating) main loop, not inside the poll thread itself.

Before this was understood, an unbound access inside `__getattr__` recursed infinitely instead of raising (fixed separately: `__getattr__` now checks the `ContextVar` directly rather than re-entering the `self` property, so unbound access is a clean, single `AttributeError` — see git history for the exact commit). That fix makes the *failure mode* sane; it does not and cannot make a `ContextVar` visible inside a thread that never had it — that's not something this design (or any `ContextVar`-based one) can paper over.

**Rule of thumb**: never read a `SelfSustaining` singleton (`Configs`/`TC`, `RabbitSubscriber`, `KafkaSubscriber`, `RedisHandler`) from code that will run inside a raw executor thread. If a blocking third-party call needs something from settings, snapshot it once at setup time (import time, or inside `__init__`, wherever construction is guaranteed to happen on a thread where the binding is visible) and close over the snapshotted value — don't defer the read into the callback that actually runs on the thread.

## Migration notes

`.self` is a read-only property now (previously a plain mutable attribute) — reads (`Configs.self.general.X`, `TC.self[tenant]`) work unchanged; writes (`Cls.self = instance`, `Cls.self = None`) need `Cls.bind(instance)` / `Cls.unbind()` instead.

- `fastloom/tenant/settings.py:61` (`GetSettingsFrom._item_getter`) and `fastloom/tenant/handler.py:34` (`get_tenant_settings`) — reads, unchanged in shape: `Configs.self.get(tenant)` / `configs.self[tenant]` (the `Configs[BaseModel, V]` generic subscript the original code used here was never doing anything — the line type-checks identically without it).
- `iam` production code: no direct `.self` access anywhere outside its own test fixtures.
- `assistant/alembic/env.py:67-68` (`TC.self.general.POSTGRES_DSN`) is a read, unaffected. Their documented `PGManager.self = None`/`CHManager.self = None` test-reset convention (`.claude/docs/conventions.md`, `tests/fixtures/postgres.py`, `tests/fixtures/redis.py`) is a write and needs `PGManager.unbind()` / `CHManager.unbind()`.

## Non-goals

- Not eliminating `from settings import TC` — that needs a custom mypy plugin to do without losing static type safety, out of scope here.
- Not making `Configs.__init__` async — Vault integration is handled as a pre-construction step instead.
- Not touching `RabbitSubscriber`/`KafkaSubscriber`/`RedisHandler`'s own internals beyond inheriting `SelfSustaining` — the same `ContextVar`-backed storage applies to them automatically.
- No shared `override()`/swap-safely context manager on the base class — see "Storage" above.
- Not flipping the shipped `TC` fixture's default scope to session — see "Test fixtures" above.
