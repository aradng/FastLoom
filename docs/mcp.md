# MCP (Model Context Protocol)

Fastloom can mount a FastMCP ASGI app inside your FastAPI service when the optional `mcp` extra is installed. The MCP server reuses your project name, your auth (via bearer forwarding), and your lifespan.

**Symbols at a glance**

- `fastloom.mcp.settings.MCPSettings` — `MCP_ENABLED`, `MCP_OPENAPI`.
- `fastloom.mcp.lifehooks.get_mcp` — the `FastMCP` singleton (lru-cached).
- `fastloom.mcp.lifehooks.get_mcp_asgi` — its ASGI app, mounted at `/mcp` inside the MCP root.
- `fastloom.mcp.lifehooks.mcp_register_app` — registers your FastAPI's OpenAPI spec as an MCP provider.
- `fastloom.mcp.lifehooks.mcp_lifespan` — composed automatically by the launcher.
- `fastloom.mcp.auth.ForwardBearerAuth`, `get_mcp_client` — internal HTTP client that forwards the incoming `Authorization` header.

## Install + enable

```bash
poetry add fastloom -E mcp -E fastapi
```

```python
# settings.py
from fastloom.mcp.settings import MCPSettings


class Settings(BaseGeneralSettings, MCPSettings, ...): ...
```

```yaml
# tenants.yaml
default:
    MCP_ENABLED: true
    MCP_OPENAPI: true   # also expose your FastAPI endpoints as MCP tools
```

When `MCP_ENABLED=True`, the launcher mounts `get_mcp_asgi()` at `FastAPISettings.API_PREFIX` (so the final MCP endpoint is `<API_PREFIX>/mcp`). The MCP lifespan is composed into the FastAPI lifespan via `combine_lifespans`, so MCP transports start and stop in step with your service.

## Defining tools

Register tools directly on the FastMCP singleton:

```python
from fastloom.mcp.lifehooks import get_mcp

mcp = get_mcp()


@mcp.tool()
async def search_products(query: str) -> list[str]:
    """Search products by name."""
    ...
```

Tool definitions must be importable before the FastAPI factory runs (typically from a module imported in `app.py`).

## Auto-expose OpenAPI as MCP tools

Setting `MCP_OPENAPI=True` triggers `mcp_register_app(app)` during the MCP lifespan startup. It adds an `OpenAPIProvider` so every FastAPI endpoint becomes an MCP tool — the provider speaks back to the FastAPI app through an in-process ASGI transport (`httpx.ASGITransport`).

`ForwardBearerAuth` copies the `Authorization` header from the inbound MCP request onto the outbound ASGI request, so auth dependencies on your routes still resolve correctly.

## Custom MCP composition

If you need a richer MCP setup (custom session state store, additional providers), construct your own `FastMCP` and mount its `.http_app(...)` via `App.mounts`:

```python
from fastmcp import FastMCP
from key_value.aio.stores.redis import RedisStore
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from fastloom.cache.lifehooks import RedisHandler
from fastloom.launcher.schemas import App
from fastloom.launcher.utils import combine_lifespans
from fastloom.tenant.settings import ConfigAlias as Configs


mcp = FastMCP(
    Configs.general.PROJECT_NAME,
    session_state_store=RedisStore(client=RedisHandler.redis),
)
mcp_app = mcp.http_app(
    "/",
    stateless_http=True,
    middleware=[
        Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"]),
    ],
)


async def my_lifespan(app):
    yield


app = App(
    mounts=[(f"{Configs.general.API_PREFIX}/mcp", mcp_app)],
    lifespan_fn=combine_lifespans(my_lifespan, mcp_app.lifespan),
    ...
)
```

When you do this manually, **do not also set `MCP_ENABLED=True`** — the launcher's auto-mount would race yours.

## Related

- [Launcher](launcher.md) — `combine_lifespans` and the startup order.
- [Auth](auth.md) — `ForwardBearerAuth` reuses the bearer flow.
