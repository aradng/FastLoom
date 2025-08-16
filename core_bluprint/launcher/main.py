import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from logging import Logger

import uvicorn
from fastapi import FastAPI
from pydantic import ValidationError
from starlette.middleware.cors import CORSMiddleware

from core_bluprint.db.settings import MongoSettings
from core_bluprint.launcher.settings import LauncherSettings
from core_bluprint.launcher.utils import (
    EndpointFilter,
    get_app,
    get_settings_cls,
)
from core_bluprint.monitoring import InitMonitoring, Instruments
from core_bluprint.observability.settings import ObservabilitySettings
from core_bluprint.settings.base import FastAPISettings, GeneralSettings
from core_bluprint.signals.depends import RabbitSubscriber, RabbitSubscriptable
from core_bluprint.signals.settings import RabbitmqSettings
from core_bluprint.tenant.settings import TenantConfigs as TC

logger: Logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    service_app = get_app()
    await service_app.load(app)
    async with service_app.lifespan_fn(app):
        yield


def initial_app():
    TC(get_settings_cls())
    logging.getLogger("uvicorn.access").addFilter(
        EndpointFilter(TC[LauncherSettings].general.LOGGING_EXCLUDED_ENDPOINTS)
    )
    if isinstance(TC[RabbitSubscriptable].general, RabbitmqSettings):
        RabbitSubscriber(TC[RabbitSubscriptable].general)
    else:
        logging.warning("Settings Does Not Inherit from RabbitmqSettings")
    # ^IMPORTANT:rabbit has to init first
    service_app = get_app()
    if (
        service_app.project_name is None
        and not TC[GeneralSettings].general.PROJECT_NAME
    ):
        raise ValidationError("PROJECT_NAME")
    if (PN := service_app.project_name) is not None and TC[
        GeneralSettings
    ].general._is_derived:
        for k in TC[GeneralSettings].settings:
            TC[GeneralSettings].settings[k].PROJECT_NAME = PN
    instruments = [Instruments.HTTPX]
    if isinstance(TC.general, RabbitmqSettings):
        instruments.append(Instruments.RABBIT)
    if isinstance(TC.general, MongoSettings):
        instruments.append(Instruments.MONGODB)
    if TC[ObservabilitySettings].general.METRICS:
        instruments.append(Instruments.METRICS)
    with InitMonitoring(
        TC[ObservabilitySettings].general, instruments=instruments
    ) as monitor:
        app = FastAPI(
            lifespan=lifespan,
            title=TC[FastAPISettings].general.PROJECT_NAME,
            docs_url=f"{TC[FastAPISettings].general.API_PREFIX}/docs",
            openapi_url=f"{TC[FastAPISettings].general.API_PREFIX}/openapi.json",
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
        service_app.root_router, prefix=TC[FastAPISettings].general.API_PREFIX
    )
    app.include_router(RabbitSubscriber.router)
    return app


app = initial_app()


def main():
    uvicorn.run(
        app="core_bluprint.launcher.main:app",
        host="0.0.0.0",
        port=TC[LauncherSettings].general.APP_PORT,
        reload=TC[LauncherSettings].general.DEBUG,
        workers=TC[LauncherSettings].general.WORKERS,
    )
