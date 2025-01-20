import json
import logging
from collections.abc import Callable, Sequence
from enum import Enum
from typing import TYPE_CHECKING, Any

import logfire
import orjson
import sentry_sdk
from jose.exceptions import JWTError
from jose.jwt import get_unverified_claims
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import (
    OTLPLogExporter,
)
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import HOST_NAME, SERVICE_NAME, Resource
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.semconv.trace import SpanAttributes
from opentelemetry.trace import Span
from pydantic import HttpUrl

from core_zenoa.observability.settings import ObservabilitySettings
from core_zenoa.tenant.protocols import TenantMonitoringSchema
from core_zenoa.utils import ColoredFormatter

if TYPE_CHECKING:
    try:
        from fastapi import FastAPI
    except ImportError:
        FastAPI = Any


def init_sentry(dsn: HttpUrl | str | None, environment: str):
    if dsn is None:
        raise ValueError("Sentry DSN is not set")
    if isinstance(dsn, HttpUrl):
        dsn = str(dsn)

    sentry_sdk.init(
        dsn=dsn,
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for performance monitoring.
        traces_sample_rate=1.0,
        enable_tracing=True,
        profiles_sample_rate=1.0,
        environment=environment,
    )


def _get_resource(settings):
    return Resource(
        attributes={
            SERVICE_NAME: settings.PROJECT_NAME,
            HOST_NAME: settings.ENVIRONMENT,
        }
    )


def get_span_proccessor() -> BatchSpanProcessor:
    return BatchSpanProcessor(OTLPSpanExporter())


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


def instrument_fastapi(app: "FastAPI"):
    from fastapi.responses import PlainTextResponse
    from fastapi.security.utils import get_authorization_scheme_param
    from starlette.exceptions import HTTPException as StarletteHTTPException

    def _server_request_hook(span: Span, scope: dict):
        if span and span.is_recording():
            if auth_header := _get_authorization_header(scope):
                scheme, param = get_authorization_scheme_param(auth_header)
                if scheme.lower() != "bearer":
                    return
                _set_user_attributes_to_span(span, param)

    def _client_response_hook(span: Span, scope: dict, message: dict):
        if span and span.is_recording():
            ...

    logfire.instrument_fastapi(
        app,
        server_request_hook=_server_request_hook,
        client_response_hook=_client_response_hook,
        meter_provider=metrics.get_meter_provider(),
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
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    otel_logger_provider = LoggerProvider(resource=_get_resource(settings))
    set_logger_provider(otel_logger_provider)
    otel_logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter())
    )

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    otel_handler = LoggingHandler(
        level=logging.DEBUG, logger_provider=otel_logger_provider
    )
    otel_handler.setFormatter(formatter)
    logger.addHandler(otel_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(ColoredFormatter())
    logger.addHandler(stream_handler)

    logfire_handler = logfire.LogfireLoggingHandler(level=logging.DEBUG)
    logfire_handler.setFormatter(formatter)
    logger.addHandler(logfire_handler)


def instrument_metrics():
    logfire.instrument_system_metrics(base="full")


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


def instrument_httpx():
    logfire.instrument_httpx(tracer_provider=trace.get_tracer_provider())


def instrument_requests():
    logfire.instrument_requests(tracer_provider=trace.get_tracer_provider())


def patch_spanbuilder_set_channel() -> None:
    """
    The default SpanBuilder.set_channel does not work with aio_pika 9.1 and the
    refactored connection attribute
    """
    import opentelemetry.instrumentation.aio_pika.span_builder
    from aio_pika.abc import AbstractChannel
    from opentelemetry.instrumentation.aio_pika.span_builder import SpanBuilder

    def set_channel(self: SpanBuilder, channel: AbstractChannel) -> None:
        if hasattr(channel, "_connection"):
            url = channel._connection.url
            port = str(url.port) or "5672"
            self._attributes.update(
                {
                    SpanAttributes.NET_PEER_NAME: url.host,
                    SpanAttributes.NET_PEER_PORT: port,
                }
            )

    opentelemetry.instrumentation.aio_pika.span_builder.SpanBuilder.set_channel = set_channel  # type: ignore[method-assign]  # noqa


def instrument_rabbit():
    from opentelemetry.instrumentation.aio_pika import AioPikaInstrumentor

    patch_spanbuilder_set_channel()
    AioPikaInstrumentor().instrument(
        tracer_provider=trace.get_tracer_provider()
    )


def instrument_mongodb():
    from bson import Decimal128, ObjectId
    from pymongo import monitoring

    def pars_mongo_types(obj: object):
        if isinstance(obj, Decimal128):
            return str(obj.to_decimal())
        if ObjectId.is_valid(obj):
            return str(obj)
        raise TypeError()

    def _response_hook(span: Span, event: monitoring.CommandSucceededEvent):
        if span and span.is_recording():
            span.set_attribute(
                "db.mongodb.server_reply",
                orjson.dumps(
                    event.reply,
                    default=pars_mongo_types,
                    option=orjson.OPT_NAIVE_UTC,
                ),
            )

    logfire.instrument_pymongo(
        tracer_provider=trace.get_tracer_provider(),
        capture_statement=True,
        response_hook=_response_hook,
    )


def instrument_openai(client: Any | None = None):
    from openai import AsyncOpenAI, OpenAI

    if client is not None and not isinstance(client, (OpenAI, AsyncOpenAI)):
        raise ValueError("client must be an instance of OpenAI or AsyncOpenAI")

    logfire.instrument_openai(client)


class Instruments(Enum):
    REDIS = instrument_redis
    CELERY = instrument_celery
    RABBIT = instrument_rabbit
    HTTPX = instrument_httpx
    REQUESTS = instrument_requests
    METRICS = instrument_metrics
    MONGODB = instrument_mongodb
    OPENAI = instrument_openai


def instrument_otel(
    settings: TenantMonitoringSchema,
    app: "FastAPI | None" = None,
    only: tuple[Instruments, ...] | None = None,
):
    logfire.configure(
        send_to_logfire=False,
        service_name=settings.PROJECT_NAME,
        console=False,
        metrics=logfire.MetricsOptions(
            additional_readers=[get_metrics_reader()]
        ),
    )

    instrument_metrics()
    instrument_logging(settings)
    if app:
        instrument_fastapi(app)
    if only is None:
        instrument_httpx()
    else:
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


class InitMonitoring:
    def __init__(
        self,
        settings: ObservabilitySettings,
        instruments: tuple[Instruments, ...] | None = None,
    ):
        self.settings = settings
        self.instruments = instruments

    def __enter__(self):
        if int(self.settings.SENTRY_ENABLED):
            init_sentry(self.settings.SENTRY_DSN, self.settings.ENVIRONMENT)

        if int(self.settings.OTEL_ENABLED):
            instrument_otel(self.settings, only=self.instruments)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb): ...

    def instrument(self, app: "FastAPI"):
        if app is not None and int(self.settings.OTEL_ENABLED):
            instrument_fastapi(app)
