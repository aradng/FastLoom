# Cache (Redis)

Fastloom uses Redis for two distinct purposes: a per-tenant settings cache (and host→tenant mapping) backed by `redis-om`, and a generic JSON cache base class for application-level use.

**Symbols at a glance**

- `fastloom.cache.settings.RedisSettings` — `REDIS_URL` (default `redis://localhost:6379/0`).
- `fastloom.cache.lifehooks.RedisHandler` — singleton holding sync + async `Redis` clients.
- `fastloom.cache.base.BaseCache` — `redis-om` `JsonModel` base.
- `fastloom.cache.base.BaseTenantSettingCache` — settings cache row (`id` primary key).
- `fastloom.cache.base.HostTenantMapping` — host → tenant index.
- `fastloom.cache.gate.RedisGuardGate` — distributed leader-election gate (context manager / decorator).
- `fastloom.cache.healthcheck.get_healthcheck`, `check_redis_connection`.

## Setup

Add `RedisSettings` to your `Settings` and turn on the healthcheck:

```python
# settings.py
class Settings(BaseGeneralSettings, RedisSettings, ...): ...

# app.py
app = App(cache_healthcheck=True, ...)
```

When `Settings` inherits `RedisSettings`, `Configs._setup_redis()` instantiates `RedisHandler(general)` and wires both `BaseCache` and the tenant-settings cache class to the shared connection. If Redis is unreachable at startup, `RedisHandler.enabled` stays `False` and the launcher silently falls back to the document / YAML tiers — the cache becomes a no-op rather than failing the boot.

## `RedisHandler`

```python
class RedisHandler(SelfSustaining):
    enabled: bool = False
    redis: Redis             # redis.asyncio.Redis
    sync_redis: SyncRedis    # redis.Redis (sync)
```

Read directly from the singleton anywhere downstream:

```python
from fastloom.cache.lifehooks import RedisHandler

if RedisHandler.enabled:
    await RedisHandler.redis.set("key", "value")
    RedisHandler.sync_redis.get("key")
```

`enabled` is set by a sync `ping()` at construction; respect it when deciding whether to use the cache as authoritative.

## Custom JSON caches

```python
from aredis_om import Field
from fastloom.cache.base import BaseCache


class UserSessionCache(BaseCache, index=True):
    class Meta:
        model_key_prefix = "user_session"

    user_id: str = Field(primary_key=True)
    expires_at: int = Field(index=True)
```

`BaseCache` extends `aredis_om.JsonModel`. Key layout is `<global_key_prefix>:<model_key_prefix>:<id>` — `global_key_prefix` defaults to `cache`. For tenant-aware cache rows, override `model_key_prefix` in your `Meta` with the project name so different services on the same Redis don't collide.

The `Configs._setup_redis()` step also rewrites the tenant settings cache's `model_key_prefix` to `<PROJECT_NAME>` for the same reason.

## Tenant-settings cache

`BaseTenantSettingCache` is the row type that `Configs.get(tenant)` consults first. You normally don't touch it directly — the system endpoints (`POST /tenant_settings`) invalidate it for you. The schema is derived dynamically from your `TenantSettings` via `pydantic.create_model`, so changes to `TenantSettings` propagate automatically.

## Host → tenant mapping

```python
class HostTenantMapping(BaseCache, index=True):
    host: str = Field(primary_key=True)
    tenant: str = Field(index=True)

    class Meta:
        model_key_prefix = "host_mapping"
```

`HeaderSource` writes into this index when a request first resolves a host to a tenant, then reads from it on subsequent requests so the YAML scan is skipped. The index is rebuilt on demand via redis-om's migrator, which the launcher runs in its internal `lifespan` when `Configs.cache_enabled`.

## Migrator

The launcher's lifespan runs `await aredis_om.Migrator().run()` when `cache_enabled` is true. This creates the secondary indexes that `redis-om` needs for `find(...)` queries. If you add `index=True` columns to your cache models, the migrator will pick them up at next boot.

## `RedisGuardGate` — single-leader work

When a service runs with `WORKERS > 1` (or as multiple replicas behind a load balancer), some startup or periodic tasks must run **at most once across the whole fleet**: data seeding, migration, schedule registration, cache warmup. `RedisGuardGate` uses a Redis `SET ... NX EX` to elect one process as the leader for a given task key.

```python
from fastloom.cache.gate import RedisGuardGate


# as a context manager — run work only if we acquired the lock
async def bootstrap():
    async with RedisGuardGate("bootstrap", ttl=30, grace=10) as acquired:
        if acquired:
            await seed_initial_data()


# as a decorator — no-op when not the leader
@RedisGuardGate("nightly_recompute", ttl=300)
async def nightly_recompute() -> int | None:
    return await rebuild_aggregates()
```

Parameters:

| Param | Purpose |
|-------|---------|
| `key` | Suffix appended to `<PROJECT_NAME>:<key>:leader` to namespace the lock per service. |
| `ttl` | Seconds the lock stays held while the function runs. Set this **longer than the worst-case runtime** of the protected code. |
| `grace` | On clean exit, the key is re-expired to this many seconds instead of being deleted. Use a non-zero grace to keep other replicas from racing back in if the work isn't actually re-runnable until some downstream timer fires. |

Semantics:

- Only the worker that wins the `NX` set runs the body. Others get `acquired=False` (or `None` return from the decorator).
- The lock holds the **PID** as its value — useful for `redis-cli get` debugging.
- If the holding process crashes, the lock expires automatically at `ttl`. Pick a `ttl` that's longer than the work but not so long that a dead leader blocks a recovery for an unacceptable window.
- The decorator always returns `T | None` — call sites have to handle the `None` (non-leader) case, even if just by ignoring it.

Use it for: lifespan-startup one-off setup, leader-elected scheduled jobs, cache rebuilds, migration steps. Don't use it as a general-purpose mutex inside a request hot path — Redis round-trips add up.

## Healthcheck

`cache_healthcheck=True` on `App` adds `get_healthcheck(REDIS_URL)` to the chain. The handler builds a fresh `Redis.from_url(...)` and `ping()`s — failure raises `RedisConnectionError`, which the `/healthcheck` endpoint converts to 503.

## Related

- [Tenant](tenant.md) — resolution order (cache → Mongo → YAML).
- [Healthcheck](healthcheck.md) — the registration chain.
- [Settings](settings.md) — adding `RedisSettings`.
