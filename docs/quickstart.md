# Quickstart

A Fastloom service is a Python project with three well-known files at its root:

- `settings.py` — declares the `Settings` class (and optionally `TenantSettings`).
- `app.py` — declares an `app: fastloom.launcher.schemas.App` instance.
- `tenants.yaml` — provides defaults under a `default:` key, plus optional per-tenant overrides.

The launcher imports these three files dynamically from the current working directory at startup. The CLI entrypoint `launch` (registered in `pyproject.toml`) runs uvicorn against `fastloom.launcher.main:app` with `factory=True`.

## 1. Install

Add fastloom with only the extras you actually need:

```bash
poetry add fastloom -E fastapi -E mongo -E rabbit -E redis -E mcp
```

Available extras: `fastapi`, `rabbit`, `kafka`, `mongo`, `redis`, `celery`, `httpx`, `requests`, `openai`, `mcp`, plus dev groups `dev` and `test`.

## 2. `settings.py`

Compose your settings class from the capability mixins you need. Field names are uppercase because they double as environment-variable names.

```python
from fastloom.db.settings import MongoSettings
from fastloom.launcher.settings import LauncherSettings
from fastloom.mcp.settings import MCPSettings
from fastloom.observability.settings import ObservabilitySettings
from fastloom.cache.settings import RedisSettings
from fastloom.settings.general import BaseGeneralSettings
from fastloom.signals.settings import RabbitmqSettings


class Settings(
    BaseGeneralSettings,    # PROJECT_NAME + ENVIRONMENT + IAM + Logging + FastAPI
    LauncherSettings,       # APP_PORT, DEBUG, WORKERS, SETTINGS_PUBLIC
    MongoSettings,          # MONGO_URI, MONGO_DATABASE
    RabbitmqSettings,       # RABBIT_URI
    RedisSettings,          # REDIS_URL
    MCPSettings,            # MCP_ENABLED, MCP_OPENAPI
    ObservabilitySettings,  # OTEL_ENABLED, SENTRY_DSN, ...
): ...


class TenantSettings(MongoSettings, RabbitmqSettings):
    """Subset of Settings that tenants may override at runtime."""
```

If `TenantSettings` is omitted, the launcher uses an empty pydantic model.

## 3. `tenants.yaml`

```yaml
default:
    ENVIRONMENT: development
    PROJECT_NAME: my_service
    APP_PORT: 8000
    DEBUG: true

    # Shared infrastructure — same database, broker, cache for every tenant.
    MONGO_URI: mongodb://mongo:27017
    MONGO_DATABASE: my_service
    RABBIT_URI: amqp://guest:guest@rabbitmq:5672/
    REDIS_URL: redis://redis:6379/0

    OTEL_ENABLED: 0
    SENTRY_ENABLED: 0

acme:
    name: acme
    website_url: "https://acme.example.com"
```

`default:` is required. Every other key is a tenant name. Tenants share the same databases — the `tenant` field on each document partitions the data. Put **non-functional and business-domain** overrides under each tenant key (hostnames, display names, feature toggles, quotas); leave infrastructure URIs in `default:` only.

## 4. `app.py`

```python
from fastapi import APIRouter
from pydantic import ValidationError

from fastloom.launcher.schemas import App

from my_service import models, signals
from my_service.api import users, billing

routes = [
    (users.router, "/users", "Users"),
    (billing.router, "/billing", "Billing"),
]


async def value_error_exception_handler(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )


app = App(
    routes=routes,
    models_module=models,      # auto-discovers Beanie Document subclasses
    signals_module=signals,    # auto-imports subscriber packages
    cache_healthcheck=True,    # adds Redis healthcheck
    exception_handlers=[
        (ValidationError, value_error_exception_handler),
    ],
)
```

Route triples are `(router, prefix, openapi_tag)`. The prefix is added on top of `FastAPISettings.API_PREFIX` (which defaults to `/api/<PROJECT_NAME>`).

## 5. Run it

```bash
# dev (uvicorn --reload when LauncherSettings.DEBUG=true)
launch

# or directly
uvicorn fastloom.launcher.main:app --factory --host 0.0.0.0 --port 8000
```

Once running:

- Swagger UI: `http://localhost:8000/api/<PROJECT_NAME>/docs`
- Healthcheck: `http://localhost:8000/healthcheck` and `http://localhost:8000/api/<PROJECT_NAME>/healthcheck`
- Tenant settings (admin): `GET /tenant_schema`, `GET /tenant_settings?tenant=acme`, `POST /tenant_settings?tenant=acme`

## Where to go next

- [Launcher & App model](launcher.md) — every field on `App` and the startup order that's load-bearing.
- [Settings & Configs](settings.md) — the `TC.general` access pattern.
- [Conventions](conventions.md) — optional-import pattern, singletons, naming.
