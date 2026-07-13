from redis.asyncio import Redis
from redis_fastapi import CacheBackend

from fastloom.cache.lifehooks import RedisHandler
from fastloom.cache.settings import RedisSettings


def test_redis_handler_exposes_decoded_bytes_and_cache_backend_clients():
    RedisHandler._self.set(None)
    try:
        handler = RedisHandler(RedisSettings())

        assert isinstance(handler.redis, Redis)
        assert isinstance(handler.redis_bytes, Redis)
        assert handler.redis is not handler.redis_bytes

        assert isinstance(handler.cache_backend, CacheBackend)
    finally:
        RedisHandler._self.set(None)
