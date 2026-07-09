import re
from typing import Annotated

from pydantic import AmqpDsn, BaseModel, BeforeValidator

from fastloom.settings.base import MonitoringSettings
from fastloom.types import Str


class RabbitmqSettings(BaseModel):
    RABBIT_URI: Str[AmqpDsn]


_BOOTSTRAP_SERVER = re.compile(r"^[\w.-]+:\d+$")


def _kafka_bootstrap(v: str) -> str:
    """librdkafka takes `host:port[,host:port]` (no scheme, no
    multi-host URI syntax). A `kafka://` prefix is stripped if present;
    each comma-separated server is validated as `host:port`."""
    v = v.removeprefix("kafka://")
    servers = v.split(",")
    if not all(_BOOTSTRAP_SERVER.match(server) for server in servers):
        raise ValueError(
            f"invalid Kafka bootstrap servers {v!r}, "
            "expected host:port[,host:port]"
        )
    return v


class KafkaSettings(BaseModel):
    KAFKA_URI: Annotated[str, BeforeValidator(_kafka_bootstrap)]


class KafkaSubscriptable(MonitoringSettings, KafkaSettings): ...
