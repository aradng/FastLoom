from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI
from fastapi.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from fastloom.mcp.auth import get_mcp_client
from fastloom.mcp.settings import MCPSettings
from fastloom.tenant.settings import ConfigAlias as Configs


@lru_cache
def get_mcp():
    from fastmcp import FastMCP

    return FastMCP(Configs[MCPSettings].general.PROJECT_NAME)


@lru_cache
def get_mcp_asgi():
    return get_mcp().http_app(
        "/mcp",
        stateless_http=True,
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["*"],
                allow_headers=["*"],
                expose_headers=["*"],
            )
        ],
    )


def mcp_register_app(app: FastAPI):
    from fastmcp.server.providers.openapi import OpenAPIProvider

    get_mcp().add_provider(
        OpenAPIProvider(
            openapi_spec=app.openapi(),
            client=get_mcp_client(app),
        )
    )


@asynccontextmanager
async def mcp_lifespan(app: FastAPI):
    if Configs[MCPSettings].general.MCP_OPENAPI:  # type: ignore[misc]
        mcp_register_app(app)

    async with get_mcp_asgi().lifespan(app):
        yield
