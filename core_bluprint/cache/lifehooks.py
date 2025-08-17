from contextlib import suppress
from os import getenv

from aredis_om import get_redis_connection
from redis import Redis
from redis.exceptions import ConnectionError

from core_bluprint.cache.settings import RedisSettings
from core_bluprint.meta import SelfSustaining


class RedisHandler(SelfSustaining):
    enabled: bool
    redis: Redis
    sync_redis: Redis

    def __init__(self):
        super().__init__()
        self.enabled = False
        settings = RedisSettings.model_validate(
            dict(redis_url=getenv("REDIS_OM_URL"))
            if getenv("REDIS_OM_URL")
            else {}
        )
        self.redis = get_redis_connection(url=str(settings.redis_url))
        self.sync_redis = Redis.from_url(url=str(settings.redis_url))
        with suppress(ConnectionError):
            self.enabled = self.sync_redis
