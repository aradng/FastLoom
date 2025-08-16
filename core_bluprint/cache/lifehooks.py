from asyncio import run
from os import getenv

from aredis_om import get_redis_connection
from redis import Redis
from redis.exceptions import ConnectionError

from core_bluprint.cache.settings import RedisSettings
from core_bluprint.meta import SelfSustaining


class RedisHandler(SelfSustaining):
    enabled: bool = False
    redis: Redis

    def __init__(self):
        super().__init__()
        settings = RedisSettings.model_validate(
            dict(redis_url=getenv("REDIS_URL")) if getenv("REDIS_URL") else {}
        )
        self.redis = get_redis_connection(url=str(settings.redis_url))
        try:
            run(self.redis.ping())
            self.enabled = True
        except ConnectionError:
            ...


RedisHandler()
