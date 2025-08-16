from aredis_om import Field, JsonModel

from core_bluprint.cache.lifehooks import RedisHandler


class BaseCache(JsonModel):
    class Meta:
        global_key_prefix = "cache"
        database = RedisHandler.redis
        model_key_prefix = "base"
        # ^should be overriden in sub


class BaseTenantSettingCache(BaseCache):
    tenant: str = Field(primary_key=True)


class HostTenantMapping(BaseCache):
    host: str = Field(primary_key=True)
    tenant: str = Field(index=True)

    class Meta:
        model_key_prefix = "host_mapping"
