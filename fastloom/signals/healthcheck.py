from collections.abc import Callable, Coroutine
from functools import partial
from typing import Any

from faststream.rabbit.fastapi import RabbitRouter


class RabbitConnectionError(Exception): ...


async def check_rabbit_connection(router: RabbitRouter) -> None:
    try:
        await router.broker.ping(timeout=5)
    except Exception as er:
        raise RabbitConnectionError(f"RabbitMQ connection error: {er}") from er


def get_healthcheck(
    router: RabbitRouter,
) -> Callable[[], Coroutine[Any, Any, None]]:
    return partial(check_rabbit_connection, router=router)
