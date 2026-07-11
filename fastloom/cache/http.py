from typing import TYPE_CHECKING

from fastapi import FastAPI
from pydantic import BaseModel

from fastloom.cache.settings import RedisSettings
from fastloom.extras import AREDIS_OM_INSTALLED
from fastloom.observability.settings import ObservabilitySettings
from fastloom.settings.base import ProjectSettings
from fastloom.tenant import Tenant
from fastloom.tenant.settings import ConfigAlias as Configs

if TYPE_CHECKING or AREDIS_OM_INSTALLED:
    from redis_fastapi import FastAPIRedis, get_settings


def scoped_eviction_group(eviction_group: str = "") -> str:
    tenant = Tenant.get(None)
    if tenant is None:
        return eviction_group
    return f"{tenant}:{eviction_group}" if eviction_group else tenant


def setup_http_cache(app: FastAPI, general: BaseModel) -> None:
    if not (AREDIS_OM_INSTALLED and isinstance(general, RedisSettings)):
        return
    settings = get_settings()
    settings.url = str(general.REDIS_URL)
    settings.prefix = Configs[ProjectSettings].general.PROJECT_NAME  # type: ignore[misc]
    builder = FastAPIRedis(app).lifespan().caching()

    observability = Configs[ObservabilitySettings].general  # type: ignore[misc]
    if isinstance(observability, ObservabilitySettings) and int(
        observability.OTEL_ENABLED
    ):
        builder.otel()
