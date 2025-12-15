from collections.abc import Callable, Coroutine
from functools import partial
from typing import Any


class RedisConnectionError(Exception): ...


async def check_redis_connection(redis_url: str) -> None:
    from redis.asyncio import Redis

    try:
        client: Redis = Redis.from_url(redis_url)
        await client.ping()
    except Exception as er:
        raise RedisConnectionError(f"Redis connection error: {er}") from er


def get_healthcheck(
    redis_url: str,
) -> Callable[[], Coroutine[Any, Any, None]]:
    return partial(check_redis_connection, redis_url=redis_url)
