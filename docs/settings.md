# Settings & Configs

Fastloom centralizes settings access via `Configs`, a class-level singleton aliased as `fastloom.tenant.settings.ConfigAlias`. Services compose a `Settings` class from capability mixins; the singleton lets any module read settings via plain `Configs.general` attribute access.

**Symbols at a glance**

- `fastloom.tenant.settings.Configs` / `ConfigAlias` — the singleton (generic over `Settings`, `TenantSettings`).
- `fastloom.settings.base.ProjectSettings`, `FastAPISettings`, `MonitoringSettings`.
- `fastloom.settings.general.BaseGeneralSettings` — bundle of `IAMSettings + LoggingSettings + MonitoringSettings + FastAPISettings`.
- `fastloom.settings.utils.pydantic_env_or_default`, `get_env_or_err` — env-var helpers.
- `fastloom.tenant.utils.load_settings`, `DEFAULT_CONFIG_KEY`, `TENANT_FILE_NAME` — YAML loader internals.

## Composing `Settings`

Inherit from the capability mixins you want. Mixins are plain pydantic models; field types and defaults are owned by them.

```python
# settings.py
from fastloom.cache.settings import RedisSettings
from fastloom.db.settings import MongoSettings
from fastloom.launcher.settings import LauncherSettings
from fastloom.mcp.settings import MCPSettings
from fastloom.observability.settings import ObservabilitySettings
from fastloom.settings.general import BaseGeneralSettings
from fastloom.signals.settings import RabbitmqSettings
from fastloom.tenant.settings import Configs
from pydantic import BaseModel


class Settings(
    BaseGeneralSettings,
    LauncherSettings,
    MongoSettings,
    RabbitmqSettings,
    RedisSettings,
    MCPSettings,
    ObservabilitySettings,
): ...


class TenantSettings(BaseModel):
    """Per-tenant overrides. Keep DB credentials, broker URIs out of here —
    those are shared across tenants."""

    name: str
    website_url: str | None = None
    # ... business-domain fields the tenant should control ...


TC: type[Configs[Settings, TenantSettings]] = Configs
```

`BaseGeneralSettings` already pulls in:

| Mixin | Provides |
|------|----------|
| `IAMSettings` | OIDC + OAuth2 + introspection knobs (see [auth.md](auth.md)) |
| `LoggingSettings` | structured logging config |
| `MonitoringSettings` | `PROJECT_NAME`, `ENVIRONMENT` |
| `FastAPISettings` | `DEBUG`, `EXCLUDED_ENDPOINTS`, computed `API_PREFIX` |

`PROJECT_NAME` defaults to the name read from the caller's `pyproject.toml` (via `infer_project_name()` in `fastloom/meta.py`), so most services don't need to set it explicitly.

## `TC` (Configs) — the universal entrypoint

The launcher builds the singleton once at startup. Everywhere else in your codebase, read the merged service settings through `TC.general`:

```python
from settings import TC

@router.get("/info")
async def info():
    return {
        "prefix": TC.general.API_PREFIX,
        "project": TC.general.PROJECT_NAME,
    }
```

`TC.general` is the **service-wide** view (defaults from `tenants.yaml` under `default:`, merged with the env). For **per-tenant** settings, see the next section.

`TC` also exposes:

| Attribute | Type | Purpose |
|-----------|------|---------|
| `TC.general` | `Settings` | Service-wide settings. |
| `TC.settings` | `dict[str, Settings]` | All tenants' merged settings, loaded at startup. |
| `TC.from_[Source]` | callable | Tenant-id dependency factory — see [tenant.md](tenant.md). |
| `TC.settings_from[Source]` | callable | Resolved tenant-settings dependency factory. |
| `TC.auth` / `TC.optional_auth` | `JWTAuth` / `OptionalJWTAuth` | Auth dependencies — see [auth.md](auth.md). |
| `TC.tenant_schema` | `SettingCacheSchema` | The dynamically-built document / cache models for `TenantSettings`. |

These are attributes on the singleton; class-level access works because of `SelfSustaining` — see [conventions.md](conventions.md#selfsustaining--class-level-singletons).

## Per-tenant settings access

To resolve the settings for one tenant:

```python
acme = await TC["acme"]              # same as: await TC.get("acme")
print(acme.website_url)
```

To persist a partial update:

```python
acme.website_url = "https://acme.example.com"
await TC.set("acme", acme)           # writes through cache + Mongo
```

Resolution order is **cache → Mongo document → in-memory `tenants.yaml`**. See [tenant.md](tenant.md) for the full chain.

Why isn't there a `TC[tenant] = value` shorthand? Pydantic's `__setitem__` would have to be sync, but `set()` writes to async Redis and Mongo. So the explicit `await TC.set(...)` call is the only form.

## Field naming

Capability fields use **SCREAMING_SNAKE_CASE** because they double as env-var names (e.g. `MONGO_URI`, `REDIS_URL`). Tenant-domain fields use snake_case. See [conventions.md](conventions.md).

## `tenants.yaml`

The launcher reads `tenants.yaml` from `cwd`. Required structure:

```yaml
default:
    ENVIRONMENT: development
    PROJECT_NAME: my_service
    APP_PORT: 8000
    DEBUG: true

    # Shared infrastructure — same for every tenant.
    MONGO_URI: mongodb://mongo:27017
    MONGO_DATABASE: my_service
    RABBIT_URI: amqp://guest:guest@rabbitmq:5672/
    REDIS_URL: redis://redis:6379/0

    OTEL_ENABLED: 0
    SENTRY_ENABLED: 0

acme:
    name: acme
    website_url: "https://acme.example.com"

beta:
    name: beta
    website_url:
        - "https://beta.example.com"
        - "https://staging.beta.example.com"
```

- The `default:` key is required. Its values seed `TC.general` and become the per-tenant baseline that overrides merge on top of.
- Every other top-level key is a tenant name. Values are merged with `default:` before validation.
- **Keep shared infrastructure (DB URIs, broker URIs, cache URLs) in `default:` only.** Databases are shared across tenants — the `tenant` field on each document does the partitioning. Per-tenant overrides should be business-domain values (names, hosts, feature toggles, quotas).
- `fastloom.tenant.utils.load_settings` parses the file via `pydantic.RootModel[dict[str, settings_cls]]`. Validation errors point to the offending tenant.

## Env-var fallbacks

Two helpers in `fastloom.settings.utils`:

```python
from typing import Annotated
from pydantic import BaseModel, BeforeValidator, Field
from fastloom.settings.utils import get_env_or_err, pydantic_env_or_default


class S(BaseModel):
    # Defaults from env var with the same name, else uses the literal default.
    MY_FIELD: Annotated[str, BeforeValidator(pydantic_env_or_default)] = "fallback"

    # Required env var; raises at validation if unset.
    MY_REQUIRED: str = Field(default_factory=get_env_or_err("MY_REQUIRED"))
```

`ObservabilitySettings.OtelConfig` uses the same idiom via `EnvBackend[T]` / `EnvDefault`.

## System settings endpoints

When the `Configs` singleton is wired, the launcher mounts these routes (always under `/`, optionally also under `API_PREFIX` if `LauncherSettings.SETTINGS_PUBLIC=True`):

- `GET /tenant_schema` — JSON Schema for `TenantSettings`.
- `GET /tenant_settings?tenant=<name>` — current resolved settings for that tenant.
- `POST /tenant_settings?tenant=<name>` — persist a partial update (merged on top of the existing document; cache is invalidated).
- `GET /reload` — touches a service file and (when not in `DEBUG`) sends `SIGHUP` to the parent process to trigger reload.

In production, leave `SETTINGS_PUBLIC` off and front the always-on routes with an auth gateway.

## Related

- [Conventions](conventions.md) — `TC` alias, `SelfSustaining` mechanics.
- [Tenant](tenant.md) — per-tenant resolution, cache → Mongo → YAML.
- [Launcher](launcher.md) — when `Configs(...)` is constructed.
