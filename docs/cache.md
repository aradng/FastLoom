# Cache (Redis)

Fastloom uses Redis for two distinct purposes: a per-tenant settings cache (and host→tenant mapping) backed by `redis-om`, and a generic JSON cache base class for application-level use.

**Symbols at a glance**

- `fastloom.cache.settings.RedisSettings` — `REDIS_URL` (default `redis://localhost:6379/0`).
- `fastloom.cache.lifehooks.RedisHandler` — singleton holding sync + async (decoded and raw-bytes) `Redis` clients, plus a `cache_backend` (see [HTTP response caching](#http-response-caching)).
- `fastloom.cache.http` — launcher wiring for `fastapi-redis-sdk` (bundled in the `redis` extra).
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

## Key naming convention

Every key fastloom writes is `{PROJECT_NAME}:{category}:...` — colon-separated, `PROJECT_NAME` always first, so services sharing one Redis instance never collide and `redis-cli --scan --pattern 'my_service:*'` gives you the whole picture. Three categories:

| Category | What lives there | Example |
|----------|-------------------|---------|
| `cache` | `BaseCache` and subclasses — structured object/JSON caching | `my_service:cache:host_mapping:{host}`, `my_service:cache:tenant_settings:{tenant_id}` |
| `http` | HTTP response caching (`fastapi-redis-sdk`) — its own sibling namespace, not just another `cache` row, since it's a different subsystem with its own TTL/eviction-group model | `my_service:http:cache:{eviction_group}:{key}` |
| `lock` | Coordination primitives that aren't cache at all (`RedisGuardGate`) | `my_service:lock:bootstrap` |

`Configs._setup_redis()` sets `global_key_prefix = f"{PROJECT_NAME}:cache"` on `BaseCache`, `BaseTenantSettingCache`, `HostTenantMapping`, and the tenant-schema cache class — you don't need to (and shouldn't) put `PROJECT_NAME` in your own `model_key_prefix`; that field is for distinguishing cache *types* within the `cache` namespace, not for cross-service scoping.

## `RedisHandler`

```python
class RedisHandler(SelfSustaining):
    enabled: bool = False
    redis: Redis             # redis.asyncio.Redis, decode_responses=True
    redis_bytes: Redis       # redis.asyncio.Redis, decode_responses=False
    sync_redis: SyncRedis    # redis.Redis (sync)
```

Read directly from the singleton anywhere downstream:

```python
from fastloom.cache.lifehooks import RedisHandler

if RedisHandler.enabled:
    await RedisHandler.redis.set("key", "value")
    RedisHandler.sync_redis.get("key")
```

`redis` decodes responses to `str` — it backs `redis-om` and is the right choice for everyday string/hash/JSON commands. `redis_bytes` is undecoded and exists specifically for raw binary payloads (e.g. a serialized Arrow/IPC buffer) where UTF-8 decoding would corrupt the data.

`enabled` is set by a sync `ping()` at construction; respect it when deciding whether to use the cache as authoritative.

`RedisHandler.cache_backend` is also set — a `CacheBackend(redis)` instance built with no `eviction_group`, since every `CacheBackend` method (`get`/`set`/`delete`/`has`/`delete_group`) takes its own `eviction_group=` override per call. One shared instance covers every group in the service; see [HTTP response caching](#http-response-caching) for how to use it for manual, cross-router invalidation.

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

`BaseCache` extends `aredis_om.JsonModel`. Key layout is `<global_key_prefix>:<model_key_prefix>:<id>` — `global_key_prefix` is rewritten to `<PROJECT_NAME>:cache` at startup (see [Key naming convention](#key-naming-convention) above), so `model_key_prefix` only needs to distinguish this cache type from others in the same service — no need to put the project name in it yourself.

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

## HTTP response caching

Fastloom wires the official [`fastapi-redis-sdk`](https://github.com/redis/fastapi-redis-sdk) into the launcher for route-level GET caching (`ETag`/`304`, `X-Redis-Cache`) with DI-based invalidation (`cache()`, `cache_evict()`, `cache_put()`). Fastloom doesn't reimplement that machinery — it only wires the SDK's connection pool onto the `REDIS_URL` you already configured. `fastapi-redis-sdk` ships as part of the `redis` extra, so nothing beyond `class Settings(..., RedisSettings, ...)` is needed — the launcher wires it whenever `RedisSettings` is present. Actual caching stays opt-in per route via `Depends(cache(...))`; there's no separate service-level toggle.

The launcher points the SDK's own key prefix at `Configs[ProjectSettings].general.PROJECT_NAME` (instead of its default `redis:fastapi`), so cache keys are namespaced per service — required since multiple fastloom services typically share one Redis instance.

When `ObservabilitySettings.OTEL_ENABLED` is on, the launcher also calls the SDK's own `.otel()` — this emits spans/metrics for the *caching layer itself* (hit/miss ratio, eviction counts, write type, latency per `eviction_group`), which is genuinely new signal on top of what `fastloom.monitoring.instrument_redis()` already gives you (raw Redis command tracing). It reads `opentelemetry.trace.get_tracer(...)`/`get_meter(...)` — the *global* provider — so it only picks up Logfire's configured pipeline because `setup_http_cache` runs inside the `InitMonitoring` context, after `logfire.configure()` has already registered it. The SDK's own `otel_redis_enabled` flag (native redis-py command instrumentation) is deliberately left off — `instrument_redis()` already covers that, and turning both on would double-instrument every Redis command.

### Manual invalidation across routers

`cache_evict()` only works for the route/group that populated the cache. When invalidation is triggered by something else entirely — a cascade delete on a foreign key, a background job, a broker signal — reach for `RedisHandler.cache_backend.delete_group(...)` directly (see [`RedisHandler`](#redishandler) above):

```python
from fastloom.cache.lifehooks import RedisHandler

async def delete_curve_share(share_id: str) -> None:
    await db.delete_share(share_id)  # FK cascade deletes junctions

    await RedisHandler.cache_backend.delete_group("curve_share")
    await RedisHandler.cache_backend.delete_group(f"junctions:{share_id}")
```

Scope `eviction_group` names per-parent (`f"junctions:{share_id}"` rather than one flat `"junctions"` group) when you need to invalidate a slice of a group rather than all of it — `delete_group` matches on a key pattern, so the resolution is whatever you bake into the group name. `fastloom.cache.http.scoped_eviction_group(eviction_group)` is available if you also want to fold `fastloom.tenant.Tenant` into that name yourself — it's a plain helper, not automatic.

For the DI factories themselves (`cache()`, `cache_evict()`, `cache_put()`, `CacheBackend.get`/`set`/`has`) see the [upstream docs](https://redis.github.io/fastapi-redis-sdk/) — fastloom only supplies the connection and prefix wiring described above.

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
| `key` | Suffix appended to `<PROJECT_NAME>:lock:<key>` to namespace the lock per service. |
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
