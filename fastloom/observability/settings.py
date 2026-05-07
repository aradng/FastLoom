from typing import Annotated, Literal

from pydantic import AnyHttpUrl, BaseModel, BeforeValidator, Field

from fastloom.settings.base import MonitoringSettings
from fastloom.settings.utils import pydantic_env_or_default
from fastloom.types import Str

type ExporterType = Literal["otlp", "console", "none"]
type MetricsExporterType = ExporterType | Literal["prometheus"]
type TracesExporterType = ExporterType | Literal["zipkin"]

type EnvBackend[T] = Annotated[T, BeforeValidator(pydantic_env_or_default)]


def EnvDefault[T](default: T):
    return Field(default=default, validate_default=True)


class OtelConfig(BaseModel):
    OTEL_EXPORTER_OTLP_ENDPOINT: EnvBackend[Str[AnyHttpUrl]] | None = (
        EnvDefault(None)
    )
    OTEL_EXPORTER_OTLP_INSECURE: EnvBackend[bool] = EnvDefault(True)
    OTEL_EXPORTER_OTLP_PROTOCOL: EnvBackend[
        Literal["grpc", "http/protobuf", "http/json"]
    ] = EnvDefault("http/protobuf")
    OTEL_LOGS_EXPORTER: EnvBackend[ExporterType] = EnvDefault("otlp")
    OTEL_METRICS_EXPORTER: EnvBackend[MetricsExporterType] = EnvDefault("otlp")
    OTEL_TRACES_EXPORTER: EnvBackend[TracesExporterType] = EnvDefault("otlp")
    # FastAPI
    OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_REQUEST: EnvBackend[
        str
    ] = EnvDefault(".*")
    OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_RESPONSE: EnvBackend[
        str
    ] = EnvDefault(".*")


class PrometheusConfig(BaseModel):
    PROMETHEUS_METRICS_ENDPOINT: EnvBackend[str] = EnvDefault("/metrics")
    PROMETHEUS_INCLUDE_IN_SCHEMA: EnvBackend[bool] = EnvDefault(True)
    PROMETHEUS_SHOULD_GZIP: EnvBackend[bool] = EnvDefault(False)
    PROMETHEUS_GROUP_STATUS_CODES: EnvBackend[bool] = EnvDefault(True)
    PROMETHEUS_IGNORE_UNTEMPLATED: EnvBackend[bool] = EnvDefault(False)
    PROMETHEUS_GROUP_UNTEMPLATED: EnvBackend[bool] = EnvDefault(True)
    PROMETHEUS_ROUND_LATENCY_DECIMALS: EnvBackend[bool] = EnvDefault(False)
    PROMETHEUS_LATENCY_DECIMALS: EnvBackend[int] = EnvDefault(4)
    PROMETHEUS_INSTRUMENT_REQUESTS_INPROGRESS: EnvBackend[bool] = EnvDefault(
        False
    )
    PROMETHEUS_INPROGRESS_NAME: EnvBackend[str] = EnvDefault(
        "http_requests_inprogress"
    )
    PROMETHEUS_INPROGRESS_LABELS: EnvBackend[bool] = EnvDefault(False)
    PROMETHEUS_MULTIPROC_DIR: EnvBackend[str] = EnvDefault("")


class ObservabilitySettings(MonitoringSettings, OtelConfig, PrometheusConfig):
    SENTRY_ENABLED: int = 0
    OTEL_ENABLED: int = 0
    PROMETHEUS_ENABLED: int = 0
    SENTRY_DSN: AnyHttpUrl | None = None
    METRICS: bool = False
