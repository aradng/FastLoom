from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from fastloom.settings.base import MonitoringSettings
from fastloom.signals.kafka.schemas import KafkaBootstrapServers


class KafkaSettings(BaseModel):
    KAFKA_URI: KafkaBootstrapServers


class KafkaSubscriptable(MonitoringSettings, KafkaSettings): ...


@runtime_checkable
class TelemetryConfigurable(Protocol):
    OTEL_ENABLED: int
