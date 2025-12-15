from contextlib import suppress
from typing import TYPE_CHECKING

from fastloom.cache.settings import RedisSettings
from fastloom.meta import SelfSustaining

_HAS_REDIS = False
with suppress(ImportError):
    from aredis_om import get_redis_connection
    from redis import Redis
    from redis.exceptions import ConnectionError

    _HAS_REDIS = True

if TYPE_CHECKING:
    from redis import Redis

if not TYPE_CHECKING and not _HAS_REDIS:
    Redis = None


class RedisHandler(SelfSustaining):
    enabled: bool = False
    redis: Redis
    sync_redis: Redis

    def __init__(self, settings: RedisSettings) -> None:
        super().__init__()
        if not _HAS_REDIS:
            return
        self.redis = get_redis_connection(url=str(settings.REDIS_URL))
        self.sync_redis = Redis.from_url(
            url=str(settings.REDIS_URL), decode_responses=True
        )
        with suppress(ConnectionError):
            self.enabled = self.sync_redis.ping()
