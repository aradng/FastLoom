from typing import TYPE_CHECKING, Any

from aio_pika import IncomingMessage
from faststream import BaseMiddleware
from faststream.broker.message import StreamMessage
from faststream.opentelemetry.middleware import (
    BaseTelemetryMiddleware,
    TelemetryMiddleware,
)
from faststream.rabbit.opentelemetry.provider import (
    RabbitTelemetrySettingsProvider,
)
from opentelemetry.metrics import Meter, MeterProvider
from opentelemetry.trace import TracerProvider
from pydantic import BaseModel

if TYPE_CHECKING:
    from faststream.types import AnyDict, AsyncFunc


def message_body_to_str(message_body) -> str:
    if isinstance(message_body, BaseModel):
        return message_body.model_dump_json()
    elif isinstance(message_body, str):
        return message_body
    else:
        return str(message_body)


class RabbitPayloadTelemetrySettingsProvider(RabbitTelemetrySettingsProvider):
    def get_publish_attrs_from_kwargs(
        self,
        kwargs: "AnyDict",
    ) -> "AnyDict":
        ret = super().get_publish_attrs_from_kwargs(kwargs)
        message_body = kwargs.pop("message_body")
        try:
            message_body_str = message_body_to_str(message_body)
        except ValueError:
            return ret
        return ret | {"messaging.message.body": message_body_str}

    def get_consume_attrs_from_message(
        self, msg: "StreamMessage[IncomingMessage]"
    ) -> "AnyDict":
        return super().get_consume_attrs_from_message(msg) | {
            "messaging.message.body": msg.body.decode()
        }


class PayloadTelemetryMiddleware(BaseTelemetryMiddleware):
    async def publish_scope(
        self, call_next: "AsyncFunc", msg: Any, *args: Any, **kwargs: Any
    ) -> Any:
        return await super().publish_scope(
            call_next, msg, *args, **(kwargs | dict(message_body=msg))
        )


class RabbitPayloadTelemetryMiddleware(TelemetryMiddleware):
    def __init__(
        self,
        *,
        tracer_provider: TracerProvider | None = None,
        meter_provider: MeterProvider | None = None,
        meter: Meter | None = None
    ) -> None:
        super().__init__(
            settings_provider_factory=(
                lambda _: RabbitPayloadTelemetrySettingsProvider()
            ),
            tracer_provider=tracer_provider,
            meter_provider=meter_provider,
            meter=meter,
            include_messages_counters=False,
        )

    def __call__(self, msg: Any | None) -> BaseMiddleware:
        return PayloadTelemetryMiddleware(
            tracer=self._tracer,
            metrics_container=self._metrics,
            settings_provider_factory=self._settings_provider_factory,
            msg=msg,
        )
