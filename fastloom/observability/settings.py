from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, Field

from fastloom.settings.base import MonitoringSettings

type ExporterType = Literal["otlp", "console", "none"]
type MetricsExporterType = ExporterType | Literal["prometheus"]
type TracesExporterType = ExporterType | Literal["zipkin"]


class OtelConfig(BaseModel):
    ENDPOINT: AnyHttpUrl | None = None
    INSECURE: bool = True
    PROTOCOL: Literal["grpc", "http/protobuf", "http/json"] = "http/protobuf"
    LOGS_EXPORTER: ExporterType = "otlp"
    METRICS_EXPORTER: MetricsExporterType = "otlp"
    TRACES_EXPORTER: TracesExporterType = "otlp"
    # FastAPI
    OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_REQUEST: str = ".*"
    OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_RESPONSE: str = ".*"


class ObservabilitySettings(MonitoringSettings):
    SENTRY_ENABLED: int = 0
    OTEL_ENABLED: int = 0
    SENTRY_DSN: AnyHttpUrl | None = None
    METRICS: bool = False
    OTEL: OtelConfig = Field(default_factory=OtelConfig)
