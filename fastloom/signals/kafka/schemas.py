from typing import Any

from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema

from fastloom.types import HostPort


class KafkaBootstrapServers(str):
    """KAFKA_URI: bare `host:port[,host:port]`, or a single `kafka://` DSN.
    Always stores/serializes as the bare form librdkafka wants."""

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        def validate(v: str) -> "KafkaBootstrapServers":
            v = v.removeprefix("kafka://")
            servers = [str(HostPort.model_validate(s)) for s in v.split(",")]
            return cls(",".join(servers))

        return core_schema.no_info_after_validator_function(
            validate,
            core_schema.str_schema(),
            serialization=core_schema.plain_serializer_function_ser_schema(
                str, return_schema=core_schema.str_schema()
            ),
        )

    @property
    def servers(self) -> list[str]:
        return self.split(",")
