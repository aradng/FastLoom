from functools import lru_cache

import httpx
from fastapi import FastAPI


class ForwardBearerAuth(httpx.Auth):
    from fastmcp.server.dependencies import get_http_headers

    def auth_flow(self, request: httpx.Request):

        forwarded = self.get_http_headers(include_all=True)
        for k, v in forwarded.items():
            request.headers[k] = v
        yield request


@lru_cache
def get_mcp_client(app: FastAPI):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        auth=ForwardBearerAuth(),
    )
