import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import lru_cache
from logging import Logger

import uvicorn
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from fastloom.cache.settings import RedisSettings
from fastloom.db.settings import MongoSettings
from fastloom.launcher.settings import LauncherSettings
from fastloom.launcher.utils import (
    EndpointFilter,
    get_app,
    get_settings_cls,
    get_tenant_cls,
    is_installed,
)
from fastloom.monitoring import InitMonitoring, Instruments
from fastloom.observability.settings import ObservabilitySettings
from fastloom.settings.base import FastAPISettings
from fastloom.signals.depends import RabbitSubscriber, RabbitSubscriptable
from fastloom.signals.settings import RabbitmqSettings
from fastloom.tenant.settings import ConfigAlias as Configs

logger: Logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    service_app = get_app()
    await service_app.load()
    if Configs.cache_enabled:
        from aredis_om import Migrator

        await Migrator().run()
    async with service_app.lifespan_fn(app):
        yield


@lru_cache
def app():
    Configs(get_settings_cls(), get_tenant_cls())
    logging.getLogger("uvicorn.access").addFilter(
        EndpointFilter(
            Configs[LauncherSettings].general.LOGGING_EXCLUDED_ENDPOINTS
        )
    )
    if isinstance(Configs[RabbitSubscriptable].general, RabbitmqSettings):
        RabbitSubscriber(Configs[RabbitSubscriptable].general)
    elif is_installed("aio-pika"):
        logging.warning("Settings Does Not Inherit from RabbitmqSettings")
    # ^IMPORTANT:rabbit has to init first
    service_app = get_app()
    instruments = [Instruments.HTTPX]
    if isinstance(Configs.general, RedisSettings):
        instruments.append(Instruments.REDIS)
    if isinstance(Configs.general, RabbitmqSettings):
        instruments.append(Instruments.RABBIT)
    if isinstance(Configs.general, MongoSettings):
        instruments.append(Instruments.MONGODB)
    if Configs[ObservabilitySettings].general.METRICS:
        instruments.append(Instruments.METRICS)
    if is_installed("pydantic-ai"):
        instruments.append(Instruments.PYDANTIC_AI)
    with InitMonitoring(
        Configs[ObservabilitySettings].general,
        instruments=instruments + service_app.additional_instruments,
    ) as monitor:
        app = FastAPI(
            lifespan=lifespan,
            title=Configs[FastAPISettings].general.PROJECT_NAME,
            docs_url=f"{Configs[FastAPISettings].general.API_PREFIX}/docs",
            redoc_url=f"{Configs[FastAPISettings].general.API_PREFIX}/redoc",
            openapi_url=f"{Configs[FastAPISettings].general.API_PREFIX}/openapi.json",
        )
        monitor.instrument(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    service_app.load_exception_handlers(app)
    service_app.load_healthchecks(app)
    service_app.load_system_endpoints(app)

    service_app.load_routes(app)
    if isinstance(Configs[RabbitSubscriptable].general, RabbitmqSettings):
        app.include_router(RabbitSubscriber.router)
    return app


def main():
    Configs(get_settings_cls(), get_tenant_cls())
    uvicorn.run(
        app=f"{__name__}:app",
        host="0.0.0.0",
        port=Configs[LauncherSettings].general.APP_PORT,
        reload=Configs[LauncherSettings].general.DEBUG,
        workers=Configs[LauncherSettings].general.WORKERS,
        factory=True,
    )
