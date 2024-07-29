from typing import TYPE_CHECKING, Any

from faststream import BaseMiddleware
from faststream.opentelemetry.middleware import (
    BaseTelemetryMiddleware,
    TelemetryMiddleware,
)
from faststream.rabbit.opentelemetry.provider import (
    RabbitTelemetrySettingsProvider,
)
from opentelemetry.metrics import Meter, MeterProvider
from opentelemetry.semconv.trace import SpanAttributes
from opentelemetry.trace import TracerProvider

if TYPE_CHECKING:
    from faststream.types import AnyDict, AsyncFunc


class RabbitPayloadTelemetrySettingsProvider(RabbitTelemetrySettingsProvider):
    def get_publish_attrs_from_kwargs(
        self,
        kwargs: "AnyDict",
    ) -> "AnyDict":
        print("OTEL_MESSAGE_PUBLISH", kwargs)
        return {
            SpanAttributes.MESSAGING_SYSTEM: self.messaging_system,
            SpanAttributes.MESSAGING_DESTINATION_NAME: kwargs.get("exchange")
            or "",
            SpanAttributes.MESSAGING_RABBITMQ_DESTINATION_ROUTING_KEY: kwargs[
                "routing_key"
            ],
            SpanAttributes.MESSAGING_MESSAGE_CONVERSATION_ID: kwargs[
                "correlation_id"
            ],
            # "messaging.message.body": kwargs.pop("msg", None) or "",
        }


class PayloadTelemetryMiddleware(BaseTelemetryMiddleware):
    async def publish_scope(
        self, call_next: "AsyncFunc", msg: Any, *args: Any, **kwargs: Any
    ) -> Any:
        return await super().publish_scope(
            call_next, msg, *args, **(kwargs | dict(msg=msg))
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
