# Healthchecks

A single `/healthcheck` endpoint runs every registered async handler in sequence and returns `200 {"status": "ok"}` on success or `503 {"detail": "..."}` on the first failure. The launcher pre-registers handlers for every capability your service has wired up; you can add service-specific handlers via `App.healthchecks`.

**Symbols at a glance**

- `fastloom.healthcheck.handler.init_healthcheck` — registers the route.
- `fastloom.db.healthcheck.get_healthcheck` / `check_mongo_connection` — Mongo ping.
- `fastloom.signals.rabbit.healthcheck.get_healthcheck` / `check_rabbit_connection` — broker ping.
- `fastloom.cache.healthcheck.get_healthcheck` / `check_redis_connection` — Redis ping.

## Auto-registered handlers

`App.load_healthchecks` adds:

| Capability | Handler | Triggered when |
|------------|---------|----------------|
| Mongo | `db.healthcheck.get_healthcheck(MONGO_URI)` | `App.models` (or `models_module`) is non-empty. |
| Rabbit | `signals.rabbit.healthcheck.get_healthcheck(router)` | `App.signals_module` is set. |
| Redis | `cache.healthcheck.get_healthcheck(REDIS_URL)` | `App(cache_healthcheck=True)`. |
| Custom | each entry in `App.healthchecks` | always. |

The route is registered once, bare (`/healthcheck`). The FastAPI instance's `root_path` (`API_PREFIX`) makes it reachable both directly — for Docker/Kubernetes probes — and through the prefixed path (`/api/<PROJECT_NAME>/healthcheck`) a gateway forwards, for proxy-routed clients.

## Adding service-specific handlers

```python
from fastloom.launcher.schemas import App

import httpx


async def check_payment_gateway() -> None:
    async with httpx.AsyncClient(timeout=2.0) as client:
        resp = await client.get("https://payment.example.com/health")
        resp.raise_for_status()


app = App(
    healthchecks=[check_payment_gateway],
    ...
)
```

A handler is any `async () -> None`. It signals failure by raising — the response body becomes `{"detail": str(exception)}`.

## Behavior

```python
@router.get(f"{prefix}/healthcheck")
async def healthcheck_endpoint() -> JSONResponse:
    try:
        for handler in healthcheck_handlers:
            await handler()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return JSONResponse(content={"status": "ok"})
```

Notes:

- Handlers run **sequentially** and bail on the first failure. Order is: your `healthchecks` first, then Redis (if enabled), then Mongo, then Rabbit.
- The endpoint is excluded from OTel by default via `FastAPISettings.EXCLUDED_ENDPOINTS` to avoid spamming traces.
- Failures don't restart the service — they only flip readiness. Let your orchestrator (k8s, docker compose) handle the rest.

## Building reusable checks

The library's built-in checks (`check_mongo_connection`, `check_rabbit_connection`, `check_redis_connection`) all follow the same pattern: open a fresh client, run a single ping with a short timeout, wrap any exception in a domain-specific error. Mirror that for custom checks — don't reuse long-lived clients in a probe (they can hide stale connection state).

## Related

- [Launcher](launcher.md) — when the route is registered.
- [Signals](signals.md), [Cache](cache.md), [db.md](db.md) — capability-specific notes.
