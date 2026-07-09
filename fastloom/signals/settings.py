import re
from typing import Annotated

from pydantic import AmqpDsn, BaseModel, BeforeValidator

from fastloom.settings.base import MonitoringSettings
from fastloom.types import Str


class RabbitmqSettings(BaseModel):
    RABBIT_URI: Str[AmqpDsn]


_BOOTSTRAP_SERVER = re.compile(r"^([A-Za-z0-9.-]+):(\d{1,5})$")


def _kafka_bootstrap(v: str) -> str:
    """librdkafka wants bare host:port[,host:port]; strips kafka://."""
    v = v.removeprefix("kafka://")
    for server in v.split(","):
        match = _BOOTSTRAP_SERVER.match(server)
        if not match or int(match.group(2)) > 65535:
            raise ValueError(
                f"invalid Kafka bootstrap servers {v!r}, "
                "expected host:port[,host:port]"
            )
    return v


class KafkaSettings(BaseModel):
    KAFKA_URI: Annotated[str, BeforeValidator(_kafka_bootstrap)]


class KafkaSubscriptable(MonitoringSettings, KafkaSettings): ...
