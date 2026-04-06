import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import lru_cache
from logging import Logger

import uvicorn
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from fastloom.launcher.settings import LauncherSettings
from fastloom.launcher.utils import (
    get_app,
    get_settings_cls,
    get_tenant_cls,
    is_installed,
)
from fastloom.logging.lifehooks import setup_logging
from fastloom.logging.settings import LoggingSettings
from fastloom.monitoring import InitMonitoring
from fastloom.observability.settings import ObservabilitySettings
from fastloom.settings.base import FastAPISettings
from fastloom.signals.depends import RabbitSubscriber, RabbitSubscriptable
from fastloom.signals.lifehooks import init_streams
from fastloom.signals.settings import RabbitmqSettings
from fastloom.tenant.settings import ConfigAlias as Configs

logger: Logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    service_app = get_app()
    await service_app.load()
    init_streams(service_app.stream_models)

    if Configs.cache_enabled:
        from aredis_om import Migrator

        await Migrator().run()

    async with service_app.lifespan_fn(app):
        yield


@lru_cache
def app():
    Configs(get_settings_cls(), get_tenant_cls())
    if isinstance(Configs[LoggingSettings].general, LoggingSettings):
        setup_logging(Configs[LoggingSettings].general)
    if isinstance(Configs[RabbitSubscriptable].general, RabbitmqSettings):
        RabbitSubscriber(Configs[RabbitSubscriptable].general)
    elif is_installed("aio-pika"):
        logging.warning("Settings Does Not Inherit from RabbitmqSettings")
    # ^IMPORTANT:rabbit has to init first
    service_app = get_app()
    with InitMonitoring(
        Configs[ObservabilitySettings].general,
        instruments=service_app.additional_instruments,
    ) as monitor:
        app = FastAPI(
            lifespan=lifespan,
            title=Configs[FastAPISettings].general.PROJECT_NAME,
            docs_url=f"{Configs[FastAPISettings].general.API_PREFIX}/docs",
            redoc_url=f"{Configs[FastAPISettings].general.API_PREFIX}/redoc",
            openapi_url=f"{Configs[FastAPISettings].general.API_PREFIX}/openapi.json",
            swagger_ui_oauth2_redirect_url=f"{Configs[FastAPISettings].general.API_PREFIX}/docs/oauth2-redirect",
            swagger_ui_init_oauth={
                "additionalQueryStringParams": {"browser": "false"},
            },
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
    service_app.load_mounts(app)
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
