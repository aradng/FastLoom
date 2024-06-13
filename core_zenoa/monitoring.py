import json
import logging
from enum import Enum
from typing import Any

import sentry_sdk
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (
    OTLPLogExporter,
)
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.instrumentation.system_metrics import (
    SystemMetricsInstrumentor,
)
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import HOST_NAME, SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span
from pydantic_settings import BaseSettings
from starlette.exceptions import HTTPException as StarletteHTTPException


def init_sentry(dsn: str):
    sentry_sdk.init(
        dsn=dsn,
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for performance monitoring.
        traces_sample_rate=1.0,
        enable_tracing=True,
        profiles_sample_rate=1.0,
    )


def _get_resource(settings: BaseSettings):
    return Resource(
        attributes={
            SERVICE_NAME: settings.PROJECT_NAME,
            HOST_NAME: settings.ENVIRONMENT,
        }
    )


def init_tracer(settings: BaseSettings):
    trace_provider = TracerProvider(resource=_get_resource(settings))
    processor = BatchSpanProcessor(
        OTLPSpanExporter(
            endpoint=f"http://{settings.OTEL_EXPORTER_OTLP_ENDPOINT}/v1/traces"
        )
    )
    trace_provider.add_span_processor(processor)
    trace.set_tracer_provider(trace_provider)


def init_metrics(settings: BaseSettings):
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(
            endpoint=(
                f"http://{settings.OTEL_EXPORTER_OTLP_ENDPOINT}/v1/metrics"
            )
        )
    )
    meter_provider = MeterProvider(
        resource=_get_resource(settings), metric_readers=[reader]
    )
    metrics.set_meter_provider(meter_provider)


def instrument_fastapi(app):
    from fastapi.responses import PlainTextResponse
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    def _server_request_hook(span: Span, scope: dict):
        if span and span.is_recording():
            ...

    def _client_response_hook(span: Span, message: dict):
        if span and span.is_recording():
            ...

    FastAPIInstrumentor().instrument_app(
        app,
        server_request_hook=_server_request_hook,
        client_response_hook=_client_response_hook,
        meter_provider=metrics.get_meter_provider(),
        tracer_provider=trace.get_tracer_provider(),
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


def instrument_logging(settings: BaseSettings):
    _logger = logging.getLogger()

    logger_provider = LoggerProvider(resource=_get_resource(settings))
    set_logger_provider(logger_provider)

    exporter = OTLPLogExporter(
        endpoint=f"http://{settings.OTEL_EXPORTER_OTLP_ENDPOINT_GRPC}/v1/logs",
    )
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    handler = LoggingHandler(
        level=logging.DEBUG, logger_provider=logger_provider
    )
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    _logger.addHandler(handler)

    _stream_handler = logging.StreamHandler()
    _stream_handler.setFormatter(formatter)
    _logger.addHandler(_stream_handler)


def instrument_metrics():
    SystemMetricsInstrumentor().instrument(
        meter_provider=metrics.get_meter_provider()
    )


def instrument_redis():
    from opentelemetry.instrumentation.redis import RedisInstrumentor

    RedisInstrumentor().instrument(tracer_provider=trace.get_tracer_provider())


def instrument_celery():
    from opentelemetry.instrumentation.celery import CeleryInstrumentor

    CeleryInstrumentor().instrument(
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
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    HTTPXClientInstrumentor().instrument(
        tracer_provider=trace.get_tracer_provider()
    )


def instrument_rabbit():
    from opentelemetry.instrumentation.aio_pika import AioPikaInstrumentor

    AioPikaInstrumentor().instrument(
        tracer_provider=trace.get_tracer_provider()
    )


class Instruments(Enum):
    REDIS = instrument_redis
    CELERY = instrument_celery
    CONFLUENT_KAFKA = instrument_confluent_kafka
    RABBIT = instrument_rabbit
    HTTPX = instrument_httpx


def instrument_otel(
    settings: BaseSettings,
    app: Any | None = None,
    only: tuple[Instruments, ...] | None = None,
):
    init_metrics(settings)
    instrument_metrics()
    init_tracer(settings)
    instrument_logging(settings)
    if app:
        instrument_fastapi(app)
    if only is None:
        instrument_redis()
        instrument_celery()
        instrument_httpx()
    else:
        for instrument in only:
            if callable(instrument):
                instrument()
            else:
                instrument.value()
