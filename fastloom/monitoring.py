import contextlib
import json
import logging
import os
import re
import shutil
from collections.abc import Callable, Sequence
from enum import Enum
from os import getenv
from typing import TYPE_CHECKING, Any

import logfire
from jose.exceptions import JWTError
from jose.jwt import get_unverified_claims
from opentelemetry import metrics, trace
from opentelemetry.context import attach, detach, set_value
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.instrumentation.utils import _SUPPRESS_INSTRUMENTATION_KEY
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.trace import Span
from pydantic import AnyHttpUrl, BaseModel
from sentry_sdk import init as sentry_init

from fastloom.cache.settings import RedisSettings
from fastloom.db.settings import MongoSettings
from fastloom.launcher.utils import is_installed
from fastloom.observability.settings import (
    ObservabilitySettings,
    OtelConfig,
    PrometheusConfig,
)
from fastloom.settings.base import FastAPISettings
from fastloom.signals.settings import RabbitmqSettings
from fastloom.tenant.protocols import TenantMonitoringSchema

if TYPE_CHECKING:
    with contextlib.suppress(ImportError):
        from fastapi import FastAPI

if not TYPE_CHECKING:
    try:
        from fastapi import FastAPI
    except ImportError:
        from typing import Any as FastAPI


def init_sentry(dsn: AnyHttpUrl | str | None, environment: str):
    if dsn is None:
        return
    if isinstance(dsn, AnyHttpUrl):
        dsn = str(dsn)

    sentry_init(
        dsn=dsn,
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for performance monitoring.
        enable_tracing=True,
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
        profile_session_sample_rate=1.0,
        profile_lifecycle="trace",
        environment=environment,
        send_default_pii=True,
    )


def get_metrics_reader() -> PeriodicExportingMetricReader:
    return PeriodicExportingMetricReader(OTLPMetricExporter())


def _get_authorization_header(scopes: dict[str, Any]) -> str | None:
    headers: dict[str, Any] = {
        key.lower().decode("latin-1"): value.decode("latin-1")
        for key, value in scopes["headers"]
    }
    if "authorization" not in headers:
        return None
    return headers["authorization"]


def _set_user_attributes_to_span(span: Span, token: str):
    try:
        payload: dict[str, Any] = get_unverified_claims(token)
        span.set_attribute("username", payload["name"])
        span.set_attribute("user_id", payload["sub"])
        span.set_attribute("tenant", payload["owner"])
    except (JWTError, KeyError):
        return


class SuppressOtelForPathsMiddleware:
    def __init__(self, app, patterns: tuple[re.Pattern | str, ...]):
        self.app = app
        self.patterns = [re.compile(p) for p in patterns]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")

        if not any(pattern.search(path) for pattern in self.patterns):
            return await self.app(scope, receive, send)

        token = attach(set_value(_SUPPRESS_INSTRUMENTATION_KEY, True))
        try:
            return await self.app(scope, receive, send)
        finally:
            detach(token)


def instrument_fastapi(app: FastAPI, settings: FastAPISettings | None = None):
    from fastapi.responses import PlainTextResponse
    from fastapi.security.utils import get_authorization_scheme_param
    from starlette.exceptions import HTTPException as StarletteHTTPException

    def _server_request_hook(span: Span, scope: dict):
        if (
            span
            and span.is_recording()
            and (auth_header := _get_authorization_header(scope))
        ):
            scheme, param = get_authorization_scheme_param(auth_header)
            if scheme.lower() != "bearer":
                return
            _set_user_attributes_to_span(span, param)

    def _client_response_hook(span: Span, scope: dict, message: dict):
        if span and span.is_recording():
            ...

    if settings and settings.EXCLUDED_ENDPOINTS:
        app.add_middleware(
            SuppressOtelForPathsMiddleware,
            patterns=settings.EXCLUDED_ENDPOINTS,
        )

    logfire.instrument_fastapi(
        app,
        server_request_hook=_server_request_hook,
        client_response_hook=_client_response_hook,
        meter_provider=metrics.get_meter_provider(),
        excluded_urls=settings.EXCLUDED_ENDPOINTS if settings else None,
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request, exc: StarletteHTTPException):
        current_span = trace.get_current_span()
        if current_span is not None and current_span.is_recording():
            current_span.set_attributes(
                {
                    "http.status_text": str(exc.detail),
                    "otel.status_description": (
                        f"{exc.status_code} / {str(exc.detail)}"
                    ),
                    "otel.status_code": "ERROR",
                }
            )
        return PlainTextResponse(
            json.dumps({"detail": str(exc.detail)}),
            status_code=exc.status_code,
        )


def instrument_logging(settings):
    class AttributedLogfireLoggingHandler(logfire.LogfireLoggingHandler):
        def fill_attributes(self, record: logging.LogRecord):
            record.SERVICE_NAME = settings.PROJECT_NAME
            record.HOST_NAME = settings.ENVIRONMENT
            return super().fill_attributes(record)

    logger = logging.getLogger()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    logfire_handler = AttributedLogfireLoggingHandler()
    logfire_handler.setFormatter(formatter)
    logger.addHandler(logfire_handler)


def instrument_metrics():
    logfire.instrument_system_metrics(base="basic")


def instrument_httpx():
    logfire.instrument_httpx(tracer_provider=trace.get_tracer_provider())


def instrument_requests():
    logfire.instrument_requests(tracer_provider=trace.get_tracer_provider())


def instrument_redis():
    logfire.instrument_redis(
        capture_statement=True, tracer_provider=trace.get_tracer_provider()
    )


def instrument_celery():
    logfire.instrument_celery(
        tracer_provider=trace.get_tracer_provider(),
        meter_provider=metrics.get_meter_provider(),
    )


def instrument_confluent_kafka():
    from opentelemetry.instrumentation.confluent_kafka import (
        ConfluentKafkaInstrumentor,
    )

    ConfluentKafkaInstrumentor().instrument(
        tracer_provider=trace.get_tracer_provider()
    )


def instrument_rabbit():
    from opentelemetry.instrumentation.aio_pika import AioPikaInstrumentor

    AioPikaInstrumentor().instrument(
        tracer_provider=trace.get_tracer_provider()
    )


def instrument_mongodb():
    from fastloom.db.monitoring import response_hook

    logfire.instrument_pymongo(
        tracer_provider=trace.get_tracer_provider(),
        capture_statement=True,
        response_hook=response_hook,
    )


def instrument_openai(client: Any | None = None):
    from openai import AsyncOpenAI, OpenAI

    if client is not None and not isinstance(client, (OpenAI, AsyncOpenAI)):
        raise ValueError("client must be an instance of OpenAI or AsyncOpenAI")

    logfire.instrument_openai(client)


def instrument_pydantic():
    logfire.instrument_pydantic()


def instrument_pydantic_ai():
    logfire.instrument_pydantic_ai()


def instrument_prometheus(
    settings: ObservabilitySettings,
    prefix: str = "",
    app: FastAPI | None = None,
):
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator(
        should_group_status_codes=settings.PROMETHEUS_GROUP_STATUS_CODES,
        should_ignore_untemplated=settings.PROMETHEUS_IGNORE_UNTEMPLATED,
        should_group_untemplated=settings.PROMETHEUS_GROUP_UNTEMPLATED,
        should_round_latency_decimals=settings.PROMETHEUS_ROUND_LATENCY_DECIMALS,
        should_instrument_requests_inprogress=settings.PROMETHEUS_INSTRUMENT_REQUESTS_INPROGRESS,
        round_latency_decimals=settings.PROMETHEUS_LATENCY_DECIMALS,
        inprogress_name=settings.PROMETHEUS_INPROGRESS_NAME,
        inprogress_labels=settings.PROMETHEUS_INPROGRESS_LABELS,
    ).instrument(app).expose(
        app,
        endpoint=f"{prefix}{settings.PROMETHEUS_METRICS_ENDPOINT}",
        include_in_schema=settings.PROMETHEUS_INCLUDE_IN_SCHEMA,
        should_gzip=settings.PROMETHEUS_SHOULD_GZIP,
    )


class Instruments(Enum):
    REDIS = instrument_redis
    CELERY = instrument_celery
    RABBIT = instrument_rabbit
    HTTPX = instrument_httpx
    PROMETHEUS = instrument_prometheus
    REQUESTS = instrument_requests
    METRICS = instrument_metrics
    MONGODB = instrument_mongodb
    PYDANTIC = instrument_pydantic
    PYDANTIC_AI = instrument_pydantic_ai
    OPENAI = instrument_openai


def instrument_otel(
    settings: TenantMonitoringSchema,
    app: FastAPI | None = None,
    only: Sequence[Instruments] = (),
    sampling: logfire.SamplingOptions | None = None,
):
    logfire.configure(
        send_to_logfire="if-token-present",
        service_name=settings.PROJECT_NAME,
        environment=settings.ENVIRONMENT,
        distributed_tracing=True,
        sampling=sampling,
        console=False,
        metrics=logfire.MetricsOptions(
            additional_readers=[get_metrics_reader()]
        )
        if getenv("OTEL_EXPORTER_OTLP_ENDPOINT") is not None
        else None,
    )

    instrument_logging(settings)
    if app:
        instrument_fastapi(app)
    for item in only:
        instrument: Instruments
        args: Sequence[Any] | None = None
        if isinstance(item, Sequence):
            instrument, args = item
        else:
            instrument = item
        func: Callable = (
            instrument if callable(instrument) else instrument.value
        )
        func(*args) if args is not None else func()


def infer_instruments[T: BaseModel](settings: T) -> list[Instruments]:
    instruments: list[Instruments] = []
    if is_installed("httpx"):
        instruments.append(Instruments.HTTPX)
    if isinstance(settings, RedisSettings):
        instruments.append(Instruments.REDIS)
    if isinstance(settings, RabbitmqSettings):
        instruments.append(Instruments.RABBIT)
    if isinstance(settings, MongoSettings):
        instruments.append(Instruments.MONGODB)
    if isinstance(settings, ObservabilitySettings) and settings.METRICS:
        instruments.append(Instruments.METRICS)
    if isinstance(settings, Instruments.PROMETHEUS):
        instruments.append(Instruments.PROMETHEUS)
    if is_installed("pydantic_ai"):
        instruments.append(Instruments.PYDANTIC_AI)
    return instruments


def setup_otel_config(settings: ObservabilitySettings):
    otel_config = OtelConfig.model_validate(
        settings.model_dump(), extra="ignore"
    )
    for field_name, value in otel_config:
        if value is not None:
            os.environ[field_name] = str(value)


def setup_prometheus_multiproc(settings: PrometheusConfig) -> None:
    if not (path := settings.PROMETHEUS_MULTIPROC_DIR):
        return
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path)
    os.environ["PROMETHEUS_MULTIPROC_DIR"] = path


class InitMonitoring:
    def __init__(
        self,
        settings: ObservabilitySettings,
        instruments: Sequence[Instruments] = (),
        otel_sampling: logfire.SamplingOptions | None = None,
    ):
        self.settings = settings
        self.instruments = instruments
        self.otel_sampling = otel_sampling
        setup_otel_config(settings)
        setup_prometheus_multiproc(settings)

    def __enter__(self):
        if int(self.settings.SENTRY_ENABLED):
            init_sentry(self.settings.SENTRY_DSN, self.settings.ENVIRONMENT)

        if int(self.settings.OTEL_ENABLED):
            instrument_otel(
                self.settings,
                only=self.instruments + infer_instruments(self.settings),
                sampling=self.otel_sampling,
            )

        return self

    def __exit__(self, exc_type, exc_val, exc_tb): ...

    def instrument(
        self, app: FastAPI, settings: FastAPISettings | None = None
    ):
        if app is None:
            return
        if int(self.settings.OTEL_ENABLED):
            instrument_fastapi(app, settings)
        if int(self.settings.PROMETHEUS_ENABLED):
            instrument_prometheus(
                self.settings,
                prefix=self.settings.API_PREFIX,
                app=app,
            )
