from os import getppid

from pydantic import BaseModel

from fastloom.cache.base import (
    BaseCache,
    BaseTenantSettingCache,
    HostTenantMapping,
)
from fastloom.cache.gate import RedisGuardGate
from fastloom.cache.settings import RedisSettings
from fastloom.settings.base import FastAPISettings, MonitoringSettings
from fastloom.tenant.settings import Configs
from fastloom.tenant.utils import SettingCacheSchema


class _Settings(FastAPISettings, MonitoringSettings, RedisSettings):
    ENVIRONMENT: str = "test"


def test_setup_redis_scopes_all_cache_prefixes_by_project_name():
    settings = _Settings(PROJECT_NAME="my_service")

    configs = Configs.__new__(Configs)
    configs.general = settings
    configs.service_cls = _Settings
    configs.tenant_schema = SettingCacheSchema(BaseModel)

    try:
        configs._setup_redis()

        assert BaseCache.Meta.global_key_prefix == "my_service:cache"
        assert (
            BaseTenantSettingCache.Meta.global_key_prefix == "my_service:cache"
        )
        assert HostTenantMapping.Meta.global_key_prefix == "my_service:cache"
        assert HostTenantMapping.Meta.model_key_prefix == "host_mapping"
        assert (
            configs.tenant_schema.cache.Meta.global_key_prefix
            == "my_service:cache"
        )
        assert (
            configs.tenant_schema.cache.Meta.model_key_prefix
            == "tenant_settings"
        )

        Configs._var.set(configs)
        assert RedisGuardGate("bootstrap").key == "my_service:lock:bootstrap"
        assert (
            RedisGuardGate("tick_loop", scope_to_parent=True).key
            == f"my_service:lock:{getppid()}:tick_loop"
        )
    finally:
        Configs._var.set(None)
