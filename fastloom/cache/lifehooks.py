from contextlib import suppress
from typing import TYPE_CHECKING

from fastloom.cache.settings import RedisSettings
from fastloom.extras import AREDIS_OM_INSTALLED
from fastloom.meta import SelfSustaining

if TYPE_CHECKING or AREDIS_OM_INSTALLED:
    from aredis_om import get_redis_connection
    from redis import Redis as SyncRedis
    from redis.asyncio import Redis
    from redis.exceptions import ConnectionError
    from redis_fastapi import CacheBackend
else:
    SyncRedis = None
    Redis = None
    CacheBackend = None


class RedisHandler(SelfSustaining):
    enabled: bool = False
    redis: Redis
    redis_bytes: Redis
    sync_redis: SyncRedis
    cache_backend: CacheBackend

    def __init__(self, settings: RedisSettings) -> None:
        super().__init__()
        if not AREDIS_OM_INSTALLED:
            return
        self.redis = get_redis_connection(url=str(settings.REDIS_URL))
        self.redis_bytes = Redis.from_url(
            url=str(settings.REDIS_URL), decode_responses=False
        )
        self.sync_redis = SyncRedis.from_url(url=str(settings.REDIS_URL))
        with suppress(ConnectionError):
            self.enabled = self.sync_redis.ping()
        self.cache_backend = CacheBackend(self.redis)
