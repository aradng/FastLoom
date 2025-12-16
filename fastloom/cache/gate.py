from collections.abc import Awaitable
from functools import wraps
from os import getpid
from typing import Callable

from fastloom.cache.lifehooks import RedisHandler
from fastloom.settings.base import ProjectSettings
from fastloom.tenant.settings import ConfigAlias as Configs


class RedisGuardGate:
    """
    - *context manager*:
    ```
    async with RedisGuardGate("boostrap", ttl=30, grace=10) as acquired:
        if acquired:
            await lifespan_init()
    ```
    - *decorator*:
    ```
    @RedisGuardGate("boostrap", ttl=30)
    async def lifespan_init():
        ...
    ```
    """

    key: str
    ttl: int
    grace: int
    _acquired: bool = False

    def __init__(self, key: str, ttl: int = 60, grace: int = 0):
        self.key = (
            f"{Configs[ProjectSettings].general.PROJECT_NAME}:{key}:leader"  # type: ignore[misc]
        )
        self.ttl = ttl
        self.grace = grace

    def __call__[T, **P](self, func: Callable[P, Awaitable[T]]):
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T | None:
            async with self as acquired:
                if acquired:
                    return await func(*args, **kwargs)
                return None

        return wrapper

    async def _acquire(self):
        acquired = await RedisHandler.redis.set(
            self.key,
            str(getpid()),
            nx=True,
            ex=self.ttl,
        )
        return acquired is not None

    async def _release(self):
        await RedisHandler.redis.expire(self.key, self.grace)

    async def __aenter__(self) -> bool:
        self._acquired = await self._acquire()
        return self._acquired

    async def __aexit__(self, exc_type, exc, tb):
        if self._acquired:
            await self._release()
