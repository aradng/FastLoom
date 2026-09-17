from pydantic import BaseModel

from fastloom.settings.base import MonitoringSettings
from fastloom.signals.kafka.schemas import KafkaBootstrapServers


class KafkaSettings(BaseModel):
    KAFKA_URI: KafkaBootstrapServers


class KafkaSubscriptable(MonitoringSettings, KafkaSettings): ...
