---
description: Configs/TC singleton access and SelfSustaining mechanics
paths: ["**/*.py"]
---

# Configs and SelfSustaining

These two concepts are paired — `Configs` is a `SelfSustaining` subclass, and almost every misuse comes from forgetting that. Full human-facing explanation lives in `docs/conventions.md`; the rules below are what to follow when writing or reviewing code.

## Reading settings

- **Use `TC.general.FIELD` (or `Configs.general.FIELD`) — never instantiate the settings class yourself.** The launcher constructs `Configs(Settings, TenantSettings)` once at startup; everywhere else, read through the class.
- **Alias `Configs` as `TC` in `settings.py`** for ergonomics:
  ```python
  TC: type[Configs[Settings, TenantSettings]] = Configs
  ```
- **Don't write `Configs[CapabilitySettings].general` in new user code.** The library uses that form internally for PEP 695 type narrowing, but in service code plain `TC.general` is clearer. If you need narrowing for mypy, use `isinstance(TC.general, RedisSettings)`.

## Tenant-scoped settings

- **Get:** `await TC[tenant_id]` (subscript on the instance returns the coroutine from `get`).
- **Set:** `await TC.set(tenant_id, value)`. There is **no** `TC[tenant_id] = value` shorthand — Python's `__setitem__` is sync, but the write hits async Redis + Mongo.
- The resolution order is **cache → Mongo → in-memory YAML**. Don't re-implement caching or fan-out — call `TC[tenant_id]` and trust it.

## `SelfSustaining` rules

`SelfSustaining` is a metaclass-driven singleton (`fastloom/meta.py`). The class-level access (`Configs.general`, `RedisHandler.redis`, `RabbitSubscriber.router`) only works once an instance has been constructed.

- **Construct once.** `Cls(...)` stores the instance at `Cls.self`. A second `Cls(...)` call re-enters `__init__` and silently replaces the singleton — callers that captured `cls.self` early are now stale.
- **Always `super().__init__()` first** when subclassing, so attribute forwarding works.
- **Idempotency guard:** if your `__init__` needs to be safe under repeated calls, check `if self.self is not None: return` at the top.
- **Tests reset via `Cls.self = None`** before rebuilding. This is the only legitimate place to mutate `self`. See the `TC` fixture in `fastloom/test/fixtures/settings.py`.
- **Don't access class attributes before construction.** `Cls.something` before `Cls(...)` raises `AttributeError("Cls.self is not initialized")`.

## Anti-patterns

- ❌ `Settings()` — re-instantiating the settings class inside a route handler.
- ❌ `Configs[FastAPISettings].general` in new code — verbose and confusing.
- ❌ `Configs.get(tenant)` without `await` — silently returns a coroutine, fields look like methods.
- ❌ `TC[tenant_id] = value` — does nothing useful; use `await TC.set(...)`.
- ❌ Constructing `RabbitSubscriber` / `RedisHandler` / `Configs` outside the launcher.
