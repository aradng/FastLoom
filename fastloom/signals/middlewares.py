from typing import TYPE_CHECKING, Any

from faststream.opentelemetry.middleware import TelemetryMiddleware
from faststream.rabbit.opentelemetry.provider import (
    RabbitTelemetrySettingsProvider,
)
from opentelemetry.metrics import Meter, MeterProvider
from opentelemetry.trace import TracerProvider
from pydantic import BaseModel

if TYPE_CHECKING:
    from aio_pika import IncomingMessage
    from faststream.message import StreamMessage
    from faststream.rabbit.response import RabbitPublishCommand


def message_body_to_str(message_body) -> str:
    if isinstance(message_body, BaseModel):
        return message_body.model_dump_json()
    return str(message_body)


class RabbitPayloadTelemetrySettingsProvider(RabbitTelemetrySettingsProvider):
    def get_publish_attrs_from_cmd(
        self,
        kwargs: "RabbitPublishCommand",
    ) -> dict[str, Any]:
        ret = super().get_publish_attrs_from_cmd(kwargs)
        try:
            message_body_str = message_body_to_str(kwargs.body)
        except ValueError:
            return ret
        return ret | {"messaging.message.body": message_body_str}

    def get_consume_attrs_from_message(
        self, msg: "StreamMessage[IncomingMessage]"
    ) -> dict[str, Any]:
        return super().get_consume_attrs_from_message(msg) | {
            "messaging.message.body": msg.body.decode()
        }


class RabbitPayloadTelemetryMiddleware(TelemetryMiddleware):
    def __init__(
        self,
        *,
        tracer_provider: TracerProvider | None = None,
        meter_provider: MeterProvider | None = None,
        meter: Meter | None = None,
        include_messages_counters: bool = False,
    ) -> None:
        super().__init__(
            settings_provider_factory=(
                lambda _: RabbitPayloadTelemetrySettingsProvider()  # type: ignore
            ),
            tracer_provider=tracer_provider,
            meter_provider=meter_provider,
            meter=meter,
            include_messages_counters=include_messages_counters,
        )
