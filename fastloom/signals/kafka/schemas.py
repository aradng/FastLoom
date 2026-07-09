from typing import Annotated, Any

from pydantic import (
    BaseModel,
    Field,
    GetCoreSchemaHandler,
    KafkaDsn,
    StringConstraints,
    TypeAdapter,
)
from pydantic_core import core_schema


class _HostPort(BaseModel):
    host: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9.-]+$")]
    port: Annotated[int, Field(ge=1, le=65535)]

    @classmethod
    def parse(cls, v: str) -> "_HostPort":
        host, _, port = v.rpartition(":")
        return cls.model_validate({"host": host, "port": port})

    def __str__(self) -> str:
        return f"{self.host}:{self.port}"


class KafkaBootstrapServers(str):
    """KAFKA_URI: bare `host:port[,host:port]`, or a single `kafka://` DSN.
    Always stores/serializes as the bare form librdkafka wants."""

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        def validate(v: str) -> "KafkaBootstrapServers":
            if "," not in v and v.startswith("kafka://"):
                dsn = TypeAdapter(KafkaDsn).validate_python(v)
                return cls(f"{dsn.host}:{dsn.port}")
            v = v.removeprefix("kafka://")
            servers = [str(_HostPort.parse(s)) for s in v.split(",")]
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
