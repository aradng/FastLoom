from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse


def init_healthcheck(
    app: FastAPI,
    healthcheck_handlers: list[Callable[[], Coroutine[Any, Any, None]]],
    prefix: str = "",
) -> None:
    router = APIRouter()

    @router.get(f"{prefix}/healthcheck")
    async def healthcheck_endpoint() -> JSONResponse:
        for handler in healthcheck_handlers:
            await handler()

        return JSONResponse(content={"status": "ok"})

    app.include_router(router, tags=["Healthcheck"])
