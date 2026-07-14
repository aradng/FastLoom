# `SelfSustaining`: plain-attribute storage with a `bind`/`unbind`/`reset` API

## Problem

`SelfSustaining` (`fastloom/meta.py`) backs `Configs`, `RabbitSubscriber`, `KafkaSubscriber`, `RedisHandler` (and, by inheritance in consuming services, things like `assistant`'s `PGManager`/`CHManager`). Swapping settings for a test used to be a manual, per-call-site dance: `Cls.self = None` → rebuild → `Cls.self = None` again, in a `try/finally`. Every service that needs this re-derives it independently — `iam` and `assistant` each hand-wrote a nearly identical session-scoped `TC` fixture; `iam` additionally hand-wrote a conftest-module-scope loader monkeypatch to make an eager `TC = Configs(...)` binding safe under pytest collection. None of this was shared; all of it was tribal knowledge re-invented per service.

Separately: services want to write eager values (topic `StrEnum`s, `Depends(TC.auth.get_claims)`) instead of wrapper functions, and feature-flag-style testing (swapping one field between test cases, not the whole settings object) needs to not be ceremony.

## Constraints

- Type safety first — no loss of static narrowing on `Configs.general.X`.
- No singleton that can't be overridden — the pain point is the reset-dance ceremony.
- Feature-flag-style per-test settings variation stays first-class, not a rare escape hatch.
- Minimal code; no custom mypy plugin (the only way to also drop `from settings import TC` entirely, out of scope here).
- No lazy/wrapper functions in API dependencies or similar just to defer a read.
- **Visible from every execution context in the process** — this is the constraint that sank the `ContextVar` attempt below, and is now load-bearing. `SelfSustaining` instances are bound exactly once, at process startup, and read from everywhere for the rest of that process's life: HTTP request handlers, Kafka consumer callbacks, background `asyncio` tasks, raw executor threads. None of those are "the test author swapping settings mid-test" — that's the *only* place multiple bindings ever coexist, and it's inherently sequential (one test's fixture teardown always completes before the next test's setup).

## Why not `ContextVar` (tried, reverted)

An earlier version of this design backed `_self` with a `contextvars.ContextVar` instead of a plain class attribute, specifically to make the reset-dance ceremony a proper token-based `bind`/`unbind`/`reset`. It shipped as fastloom 0.4.53 and caused two separate production incidents before being reverted here:

1. **Raw executor threads.** `ContextVar` bindings propagate automatically across `asyncio.create_task`/`TaskGroup` (default context-copy) and across `asyncio.to_thread`/`anyio.to_thread.run_sync` (both explicitly `copy_context()` before handing work to the worker thread) — but **not** into a thread started via `loop.run_in_executor(...)` or a raw `concurrent.futures.ThreadPoolExecutor.submit(...)`/`threading.Thread(...).start()`, which get a fresh top-level `Context` with no memory of anything `.set()` in the calling thread. This bit `assistant/utils/tracing.py`'s `CustomSampler`: faststream's confluent-kafka transport runs `poll`/`consume`/`close`/`produce`/`commit` through a dedicated single-worker `ThreadPoolExecutor`, and OpenTelemetry's auto-instrumentation invokes the sampler from inside that same thread — reading `TC.general.X` there hit an unbound `Configs`. Worked around at the time by snapshotting the value at `__init__` instead of reading it live in the sampler callback — a real fix was deferred.
2. **The ASGI lifespan task (worse: total outage, not a narrow code path).** uvicorn's `LifespanOn.startup()` (`uvicorn/lifespan/on.py`) runs the ASGI app's lifespan — the exact place `PGManager(TC.general)`/`CHManager(TC.general)` get constructed in `assistant/core/db/lifespan.py` — inside a **forked task** (`loop.create_task(self.main())`), synchronized back to the caller only via an `asyncio.Event`. The calling code (`Server.startup()`, which later calls `create_server()` and is the ultimate ancestor of every per-request task) never inherits that forked task's `ContextVar` mutations — `.set()` inside a task only ever affects that task's own context copy and its descendants, never a sibling or an ancestor. Background `asyncio.create_task(...)` workers *created from within* the lifespan function (`tick_task`/`sync_task`/etc.) were fine — they're descendants of the binding task. Every HTTP request was not — request tasks are forked from the ASGI server's own root task, a sibling of the lifespan task, not a descendant of it. Result: `PGManager is not bound` on literally every DB-touching endpoint, on every process start, 100% reproducible, not a race — while Kafka consumers and background workers kept working, which is what made it non-obvious from watching logs alone.

Both incidents are the same mechanism (a context-local value read from outside the context lineage that set it) surfacing through different concurrency primitives. The fix isn't a smarter `ContextVar` — the constraint above ("visible from every execution context") is incompatible with a mechanism whose entire purpose is context-local isolation. Concurrent multi-binding isolation was never an actual production requirement (see Constraints); reverting to a plain, ordinary mutable class attribute for `_self` satisfies "visible everywhere" unconditionally, by construction, while keeping the `bind`/`unbind`/`reset(token)` API this design set out to provide.

## Design

### Storage

```python
from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True, slots=True)
class Token[T]:
    previous: T


class SelfSustainingMeta(type):
    def __new__(mcls, name, bases, ns):
        ns["_self"] = None
        return super().__new__(mcls, name, bases, ns)

    @property
    def self(cls):
        if (instance := cls._self) is None:
            raise AttributeError(f"{cls.__name__} is not bound")
        return instance

    def __getattr__(cls, name):
        if (instance := cls._self) is None:
            raise AttributeError(f"{cls.__name__} is not bound")
        return getattr(instance, name)

    def __setattr__(cls, name, value):
        if (instance := cls._self) is None:
            return super().__setattr__(name, value)
        return setattr(instance, name, value)


class SelfSustaining(metaclass=SelfSustainingMeta):
    def __init__(self, *args, **kwargs) -> None:
        type(self).bind(self)

    @classmethod
    def bind(cls, instance: Self) -> Token[Self | None]:
        token = Token(cls._self)
        type.__setattr__(cls, "_self", instance)
        return token

    @classmethod
    def unbind(cls) -> Token[Self | None]:
        token = Token(cls._self)
        type.__setattr__(cls, "_self", None)
        return token

    @classmethod
    def reset(cls, token: Token[Self | None]) -> None:
        type.__setattr__(cls, "_self", token.previous)
```

`Configs.general`, `TC.general.X`, `TC.from_[TokenHeaderSource]` — same syntax as always; `_self` is now an ordinary class attribute, not a `ContextVar`.

**`__new__`** still sets `_self = None` per subclass, at class-definition time, stored directly in that class's own namespace — same reason as before: `Configs`, `RabbitSubscriber`, `KafkaSubscriber`, `RedisHandler` (and `assistant`'s `PGManager`/`CHManager`) each need an independent binding, not one inherited/shared from `SelfSustaining` itself. Landing it in the `namespace` dict before `type.__new__` runs means `_self` is present in `cls.__dict__` before any `__setattr__` call can happen at all — this is what makes the "not yet bound" branch below work for `typing._generic_init_subclass`'s `cls.__parameters__` write during PEP-695-generic subclass definition (`Configs[T, V]`).

**`self`** is still a read-only property; `__getattr__` still checks `cls._self` directly rather than delegating to it, preserving the earlier recursion fix (an `AttributeError` raised from inside `__getattr__` would otherwise be reinterpreted by Python as "attribute not found, try `__getattr__` again").

**`bind`/`unbind`/`reset`** keep the exact same external shape as the `ContextVar` version — `bind(instance)` swaps in a new binding and returns a `Token` capturing whatever was there before; `unbind()` is the same but clears to `None`; `reset(token)` restores the captured value. The only change is that `Token` is now fastloom's own tiny frozen dataclass instead of `contextvars.Token`, and `bind`/`unbind`/`reset` use `type.__setattr__(cls, "_self", ...)` to write `_self` directly, bypassing `SelfSustainingMeta.__setattr__`'s own instance-forwarding branch (which would otherwise try to `setattr` the *currently bound instance* instead of rebinding `_self` itself).

No caller-visible change: every consumer of `bind`/`unbind`/`reset`/`.self` — `Configs.__init__`'s idempotency guard, `override_fields`, `tc_context`, `assistant`'s `PGManager.unbind()`/`CHManager.unbind()` test-reset convention — keeps working unmodified.

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

Test isolation works fine with a plain class attribute precisely because tests run sequentially within a process (pytest-asyncio included) — the "concurrent isolation" a `ContextVar` would buy was never exercised and was never the point; see Constraints.

### Eager values (topic names, `Depends(...)`)

`iam`'s production code does `Depends(TC.auth.get_claims)` as an eager function-default, evaluated once at import time, and it works — because `main.py`'s `app()` factory constructs `Configs`/brokers *before* `get_app()` imports any route/signal module (`fastloom/launcher/main.py:52-58`). Same principle that makes `iam`'s `constants.py` `StrEnum` topics safe: eager values are safe wherever construction demonstrably happens before anything imports the referencing module — a property of import/construction ordering, not of storage mechanism. `SelfSustaining`'s job is unaffected by *when* `Cls(...)` is called, only by *what* backs the binding once it is — and a plain class attribute makes that binding visible everywhere unconditionally, which is strictly *more* eager-value-friendly than the `ContextVar` version (it no longer matters whether the binding site and the reading site are the same task lineage).

One place discipline is still required regardless of storage mechanism: a value needed at *test-collection* time (an eager class-body constant in a test file) requires the binding to happen at conftest **module** scope, not inside a fixture (autouse or not) — pytest imports conftest.py before collecting sibling test files, but fixtures only run after the entire collection phase. `patch_tenant_loader_at_import` (`fastloom/test/fixtures/settings.py`, documented in `docs/test.md`) is the mechanism for that case.

## Verified compatibility

- **FastStream context propagation, background tasks, raw executor threads, the ASGI lifespan task**: all of these are now moot as compatibility questions — a plain class attribute is visible from literally any Python code running in the same process, regardless of which task/thread/coroutine lineage it's in. There is no propagation mechanism to verify because there's no context boundary to cross.
- **Per-tenant settings caching** (`BaseTenantSettingCache`, `HostTenantMapping`, `SettingCacheSchema`) isn't built on `SelfSustaining` at all — `Configs.get(tenant)`/`await TC[tenant]` is a method call on whichever instance `_self` currently holds, so it just works.
- **Vault-sourced settings** (future: fetch `KAFKA_URI`/`RABBIT_URI`/`MONGO_URI`/`POSTGRES_DSN`-style fields from Vault before constructing `Settings`): compatible without touching this design, same as before — see prior revision's reasoning, unaffected by the storage change.
- **Multi-process safety** (`iam` runs `WORKERS: 4`, `assistant` similarly multi-worker): plain class attributes don't cross process boundaries either — each uvicorn worker is a separate OS process with its own copy of the class object, independently importing/constructing `Configs`/`PGManager`/etc. once. Same guarantee the `ContextVar` version had here, for a different reason.

## Migration notes

`.self` is a read-only property (previously a plain mutable attribute) — reads (`Configs.self.general.X`, `TC.self[tenant]`) work unchanged; writes (`Cls.self = instance`, `Cls.self = None`) need `Cls.bind(instance)` / `Cls.unbind()` instead. This was already true under the `ContextVar` version and remains true now — nothing further to migrate.

- `fastloom/tenant/settings.py:61` (`GetSettingsFrom._item_getter`) and `fastloom/tenant/handler.py:34` (`get_tenant_settings`) — reads, unchanged in shape.
- `iam` production code: no direct `.self`/`_self` access anywhere outside its own test fixtures.
- `assistant/alembic/env.py` (`TC.self.general.POSTGRES_DSN`) is a read, unaffected. `PGManager.unbind()` / `CHManager.unbind()` (their test-reset convention) keep working unmodified.

## Non-goals

- Not eliminating `from settings import TC` — that needs a custom mypy plugin to do without losing static type safety, out of scope here.
- Not making `Configs.__init__` async — Vault integration is handled as a pre-construction step instead.
- Not touching `RabbitSubscriber`/`KafkaSubscriber`/`RedisHandler`'s own internals beyond inheriting `SelfSustaining` — the same plain-attribute-backed storage applies to them automatically.
- No shared `override()`/swap-safely context manager on the base class — `bind`/`unbind`/`reset(token)` cover every actual call site; see "Storage" above.
- Not flipping the shipped `TC` fixture's default scope to session — see "Test fixtures" above.
- Not reintroducing per-context isolation for `SelfSustaining` bindings in any form — see "Why not `ContextVar`" above. If a genuine need for concurrent, isolated bindings within one process ever materializes, it needs its own design (and almost certainly shouldn't live on the same base class production code depends on for "the" singleton).
