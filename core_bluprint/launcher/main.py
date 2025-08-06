import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from logging import Logger

import uvicorn
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from core_bluprint.launcher.settings import LauncherSettings
from core_bluprint.launcher.utils import (
    EndpointFilter,
    get_app,
    get_settings_cls,
)
from core_bluprint.monitoring import InitMonitoring, Instruments

# from core_bluprint.signals.depends import RabbitSubscriber as RR
from core_bluprint.tenant.settings import TenantConfigs as TC

logger: Logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    service_app = get_app()
    await service_app.load(app)
    async with service_app.lifespan_fn(app):
        yield


def initial_app():
    TC.load(get_settings_cls())
    logging.getLogger("uvicorn.access").addFilter(
        EndpointFilter(
            TC[LauncherSettings].general().LOGGING_EXCLUDED_ENDPOINTS
        )
    )

    # RR.load(TC.general())
    with InitMonitoring(
        TC.general(),
        instruments=(
            Instruments.HTTPX,
            Instruments.RABBIT,
            Instruments.MONGODB,
        ),
    ) as monitor:
        app = FastAPI(
            lifespan=lifespan,
            title=TC.general().PROJECT_NAME,
            docs_url=f"{TC.general().API_PREFIX}/docs",
            openapi_url=f"{TC.general().API_PREFIX}/openapi.json",
        )
        monitor.instrument(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    service_app = get_app()
    service_app.load_exception_handlers(app)
    service_app.load_healthchecks(app)

    app.include_router(get_app().root_router, prefix="/api")
    # app.include_router(RR.get().router)
    return app


app = initial_app()


def main():
    uvicorn.run(
        "core_launcher.main:app",
        host="0.0.0.0",
        port=TC.general().APP_PORT,
        reload=TC.general().DEBUG,
        workers=TC.general().WORKERS,
    )
