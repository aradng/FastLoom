import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from logging import Logger

import uvicorn
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from fastloom.db.settings import MongoSettings
from fastloom.launcher.settings import LauncherSettings
from fastloom.launcher.utils import (
    EndpointFilter,
    get_app,
    get_settings_cls,
    get_tenant_cls,
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
    await service_app.load(app)
    if Configs.cache_enabled:
        from aredis_om import Migrator

        await Migrator().run()
    async with service_app.lifespan_fn(app):
        yield


def initial_app():
    Configs(get_settings_cls(), get_tenant_cls())
    logging.getLogger("uvicorn.access").addFilter(
        EndpointFilter(
            Configs[LauncherSettings].general.LOGGING_EXCLUDED_ENDPOINTS
        )
    )
    if isinstance(Configs[RabbitSubscriptable].general, RabbitmqSettings):
        RabbitSubscriber(Configs[RabbitSubscriptable].general)
    else:
        logging.warning("Settings Does Not Inherit from RabbitmqSettings")
    # ^IMPORTANT:rabbit has to init first
    service_app = get_app()
    instruments = [Instruments.HTTPX, Instruments.REDIS]
    if isinstance(Configs.general, RabbitmqSettings):
        instruments.append(Instruments.RABBIT)
    if isinstance(Configs.general, MongoSettings):
        instruments.append(Instruments.MONGODB)
    if Configs[ObservabilitySettings].general.METRICS:
        instruments.append(Instruments.METRICS)
    with InitMonitoring(
        Configs[ObservabilitySettings].general, instruments=instruments
    ) as monitor:
        app = FastAPI(
            lifespan=lifespan,
            title=Configs[FastAPISettings].general.PROJECT_NAME,
            docs_url=f"{Configs[FastAPISettings].general.API_PREFIX}/docs",
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

    app.include_router(
        service_app.root_router,
        prefix=Configs[FastAPISettings].general.API_PREFIX,
    )
    if isinstance(Configs[RabbitSubscriptable].general, RabbitmqSettings):
        app.include_router(RabbitSubscriber.router)
    return app


app = initial_app()


def main():
    uvicorn.run(
        app=f"{__name__}:app",
        host="0.0.0.0",
        port=Configs[LauncherSettings].general.APP_PORT,
        reload=Configs[LauncherSettings].general.DEBUG,
        workers=Configs[LauncherSettings].general.WORKERS,
    )
