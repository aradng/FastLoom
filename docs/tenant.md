# Tenant

Multi-tenancy is first-class in Fastloom: every request can carry a tenant identifier, and per-tenant settings are resolved through a three-tier chain. The `Configs` singleton owns this resolution; `fastloom.tenant.depends` provides DI sources for extracting the tenant from incoming requests.

**Symbols at a glance**

- `fastloom.tenant.settings.Configs` / `ConfigAlias` — the singleton (also documented in [settings.md](settings.md)).
- `fastloom.tenant.Tenant` — a `ContextVar[str]` set by the source dependencies.
- `fastloom.tenant.handler.init_settings_endpoints` — registers `/tenant_schema`, `/tenant_settings`, `/reload`.
- `fastloom.tenant.schemas.TenantMixin` — `tenant: str` field for Beanie documents.
- `fastloom.tenant.schemas.BaseTenantWithHostSettings` — `website_url` field for host-based tenant routing.
- Source classes in `fastloom.tenant.depends`: `HeaderSource`, `PathSource`, `TokenHeaderSource`, `OptionalTokenHeaderSource`, `TokenBodySource`, `ContextSource`.
- `fastloom.tenant.depends.TenantNotFound`, `TenantDependancySelector`, `BaseGetFrom`.

## Resolution order

`TC.get(tenant)` (also reachable as `await TC[tenant]`) walks three tiers, returning the first hit:

1. **Redis cache** (`BaseTenantSettingCache`) — when `RedisSettings` is in the mix and the connection works.
2. **MongoDB document** (`BaseTenantSettingsDocument`) — when `MongoSettings` is in the mix.
3. **In-memory `tenants.yaml` map** — populated at startup.

On cache miss + Mongo hit, the result is written back to the cache. `await TC.set(tenant, value)` strips defaults (so the persisted document only contains real overrides) and writes through both cache and Mongo. There is no `TC[tenant] = value` shorthand — Python `__setitem__` is synchronous, and the write needs to await async clients.

```python
# Read
cfg = await TC["acme"]

# Write
cfg.website_url = "https://acme.example.com"
await TC.set("acme", cfg)
```

## Tenant DI sources

The launcher wires `Configs.from_` as a `TenantDependancySelector` that knows about six source classes. Pick the one that matches how your tenant identifier reaches the service:

| Source | Reads from | Use when |
|--------|------------|----------|
| `HeaderSource` | `X-Forwarded-Host` header | Reverse proxy adds a host header; tenants are mapped by website domain. |
| `PathSource` | URL path parameter `{tenant}` | Tenant is part of the route. |
| `TokenHeaderSource` | OIDC bearer token (required) | Tenant lives in the issuer URL of the JWT (`UserClaims.tenant`). |
| `OptionalTokenHeaderSource` | OIDC bearer token (optional) | Same as above but the route is publicly accessible. |
| `TokenBodySource` | `token` field in the JSON body | Webhook-style routes that pass a token in the payload. |
| `ContextSource` | FastStream rabbit message context | RabbitMQ subscriber needs the publishing tenant. |

Inject a source-bound tenant dependency like this:

```python
from typing import Annotated
from fastapi import APIRouter, Depends
from fastloom.tenant.depends import TokenHeaderSource

from settings import TC

router = APIRouter()


@router.get("/me")
async def me(
    tenant: Annotated[str, Depends(TC.from_[TokenHeaderSource])],
) -> dict[str, str]:
    return {"tenant": tenant}
```

For the resolved tenant *settings* (the full `TenantSettings` instance):

```python
@router.get("/config")
async def config(
    settings: Annotated[TenantSettings, Depends(TC.settings_from[TokenHeaderSource])],
):
    return settings
```

All source dependencies also set `fastloom.tenant.Tenant` (a `ContextVar`), so you can read the current tenant from background tasks or signal handlers without re-injecting it.

## Storing data per tenant

Add `TenantMixin` to any Beanie document that should be tenant-scoped:

```python
from beanie import Document
from fastloom.tenant.schemas import TenantMixin


class Order(Document, TenantMixin):
    class Settings:
        name = "orders"

    item: str
    quantity: int
```

Combine with `CreatedUpdatedAtSchema` and add an index over `(tenant, ...)` so queries can be tenant-scoped efficiently.

## Host-based routing

When tenants are identified by domain, declare your `TenantSettings` extending `BaseTenantWithHostSettings`:

```python
from fastloom.tenant.schemas import BaseTenantWithHostSettings


class TenantSettings(BaseTenantWithHostSettings):
    name: str
```

```yaml
acme:
    name: acme
    website_url: "https://acme.example.com"

beta:
    name: beta
    website_url:
        - "https://beta.example.com"
        - "https://staging.beta.example.com"
```

`HeaderSource` builds a `host → tenant` map at startup and (when Redis is configured) caches it as `HostTenantMapping` for the request hot path.

## System endpoints

`init_settings_endpoints` is invoked by the launcher and exposes:

- `GET /tenant_schema` — JSON Schema for `TenantSettings`.
- `GET /tenant_settings?tenant=<name>` — current resolved settings.
- `POST /tenant_settings?tenant=<name>` — partial update merged with the existing document; cache invalidated.
- `GET /reload` — triggers uvicorn reload (touches a service file).

These are always mounted at the root; set `LauncherSettings.SETTINGS_PUBLIC=True` to also mount them under `API_PREFIX`. Treat the always-on root paths as admin-only.

## Related

- [Settings](settings.md) — composing the `Settings` class.
- [Auth](auth.md) — how `UserClaims.tenant` is derived.
- [Cache](cache.md) — `HostTenantMapping` and tenant settings cache.
