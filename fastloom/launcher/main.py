import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import lru_cache
from logging import Logger

import uvicorn
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from fastloom.cache.http import setup_http_cache
from fastloom.cache.settings import RedisSettings
from fastloom.launcher.settings import LauncherSettings
from fastloom.launcher.utils import (
    combine_lifespans,
    get_app,
    get_settings_cls,
    get_tenant_cls,
    setup_brokers,
)
from fastloom.logging.lifehooks import setup_logging
from fastloom.logging.settings import LoggingSettings
from fastloom.mcp.lifehooks import get_mcp_asgi, mcp_lifespan
from fastloom.mcp.settings import MCPSettings
from fastloom.monitoring import InitMonitoring
from fastloom.observability.settings import ObservabilitySettings
from fastloom.settings.base import FastAPISettings
from fastloom.signals.depends import RabbitSubscriber, RabbitSubscriptable
from fastloom.signals.kafka.depends import KafkaSubscriber
from fastloom.signals.kafka.settings import KafkaSettings, KafkaSubscriptable
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

    yield


@lru_cache
def app():
    Configs(get_settings_cls(), get_tenant_cls())
    if isinstance(Configs[LoggingSettings].general, LoggingSettings):
        setup_logging(Configs[LoggingSettings].general)
    setup_brokers()
    service_app = get_app()
    lifespans = [lifespan]
    if isinstance(Configs[MCPSettings].general, MCPSettings):
        lifespans.append(mcp_lifespan)
    with InitMonitoring(
        Configs[ObservabilitySettings].general,
        instruments=service_app.additional_instruments,
        otel_sampling=service_app.otel_sampling,
    ) as monitor:
        app = FastAPI(
            lifespan=combine_lifespans(
                *(lifespans + [service_app.lifespan_fn])
            ),
            title=Configs[FastAPISettings].general.PROJECT_NAME,
            root_path=Configs[FastAPISettings].general.API_PREFIX,
            docs_url="/docs",
            redoc_url="/redoc",
            openapi_url="/openapi.json",
            swagger_ui_oauth2_redirect_url="/docs/oauth2-redirect",
            swagger_ui_init_oauth={
                "additionalQueryStringParams": {"browser": "false"},
            },
        )
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        setup_http_cache(app, Configs[RedisSettings].general)
        service_app.load_exception_handlers(app)
        service_app.load_healthchecks(app)
        service_app.load_system_endpoints(app)

        service_app.load_routes(app)
        service_app.load_mounts(app)
        if (
            isinstance(Configs[MCPSettings].general, MCPSettings)
            and Configs[MCPSettings].general.MCP_ENABLED
        ):
            app.mount("/", get_mcp_asgi())
        if isinstance(Configs[RabbitSubscriptable].general, RabbitmqSettings):
            app.include_router(RabbitSubscriber.router)
        if isinstance(Configs[KafkaSubscriptable].general, KafkaSettings):
            app.include_router(KafkaSubscriber.router)
        monitor.instrument(app, Configs[FastAPISettings].general)
        # NOTE: FastAPI instrumentation has to be after
        # all middlewares and routes are loaded
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
