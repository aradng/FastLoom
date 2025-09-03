from aredis_om import Field, JsonModel

from fastloom.cache.lifehooks import RedisHandler

RedisHandler()


class BaseCache(JsonModel):
    class Meta:
        global_key_prefix = "cache"
        database = RedisHandler.redis
        model_key_prefix = "base"
        # ^should be overriden in sub

    @property
    async def invalidate(self):
        return await self.expire(0)


class BaseTenantSettingCache(BaseCache):
    id: str = Field(primary_key=True)


class HostTenantMapping(BaseCache, index=True):  # type: ignore[call-arg]
    host: str = Field(primary_key=True)
    tenant: str = Field(index=True)

    class Meta:
        model_key_prefix = "host_mapping"
