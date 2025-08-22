import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from logging import Logger

import uvicorn
from aredis_om import Migrator
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from core_bluprint.db.settings import MongoSettings
from core_bluprint.launcher.settings import LauncherSettings
from core_bluprint.launcher.utils import (
    EndpointFilter,
    get_app,
    get_settings_cls,
    get_tenant_cls,
)
from core_bluprint.monitoring import InitMonitoring, Instruments
from core_bluprint.observability.settings import ObservabilitySettings
from core_bluprint.settings.base import FastAPISettings
from core_bluprint.signals.depends import RabbitSubscriber, RabbitSubscriptable
from core_bluprint.signals.settings import RabbitmqSettings
from core_bluprint.tenant.settings import ConfigAlias as Configs

logger: Logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    service_app = get_app()
    await service_app.load(app)
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

    app.include_router(
        service_app.root_router,
        prefix=Configs[FastAPISettings].general.API_PREFIX,
    )
    app.include_router(RabbitSubscriber.router)
    return app


app = initial_app()


def main():
    uvicorn.run(
        app="core_bluprint.launcher.main:app",
        host="0.0.0.0",
        port=Configs[LauncherSettings].general.APP_PORT,
        reload=Configs[LauncherSettings].general.DEBUG,
        workers=Configs[LauncherSettings].general.WORKERS,
    )
