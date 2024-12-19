from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse


def init_healthcheck(
    app: FastAPI,
    healthcheck_handlers: list[
        tuple[
            Callable[..., Coroutine[Any, Any, None]],
            list[Any] | dict[str, Any] | None,
        ]
    ],
    prefix: str | None = None,
) -> None:
    async def healthcheck_endpoint() -> JSONResponse:
        errors: list[str] = []
        for handler_tuple in healthcheck_handlers:
            handler = handler_tuple[0]
            try:
                args = (
                    handler_tuple[1]
                    if len(handler_tuple) > 1
                    and isinstance(handler_tuple[1], list)
                    else []
                )
                kwargs = (
                    handler_tuple[1]
                    if len(handler_tuple) > 1
                    and isinstance(handler_tuple[1], dict)
                    else {}
                )
                await handler(*args, **kwargs)
            except Exception as er:
                errors.append(str(er))

        if errors:
            return JSONResponse(content=errors, status_code=500)
        return JSONResponse(content={"status": "ok"})

    route_path: str = f"{prefix}/healthcheck" if prefix else "/healthcheck"
    app.add_api_route(route_path, healthcheck_endpoint, methods=["GET"])
