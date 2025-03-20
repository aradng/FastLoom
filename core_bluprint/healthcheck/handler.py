from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse


def init_healthcheck(
    app: FastAPI,
    healthcheck_handlers: tuple[Callable[..., Coroutine[Any, Any, None]], ...],
    prefix: str = "",
) -> None:
    async def healthcheck_endpoint() -> JSONResponse:
        for handler in healthcheck_handlers:
            await handler()

        return JSONResponse(content={"status": "ok"})

    app.add_api_route(
        f"{prefix}/healthcheck", healthcheck_endpoint, methods=["GET"]
    )
