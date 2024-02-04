from functools import lru_cache

from redis.asyncio.client import Redis


@lru_cache
def get_redis(url: str) -> Redis:
    return Redis.from_url(url)
