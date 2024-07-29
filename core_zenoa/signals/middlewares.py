from typing import TYPE_CHECKING

from faststream.opentelemetry.middleware import TelemetryMiddleware
from faststream.rabbit.opentelemetry.provider import (
    RabbitTelemetrySettingsProvider,
)
from opentelemetry.metrics import Meter, MeterProvider
from opentelemetry.semconv.trace import SpanAttributes
from opentelemetry.trace import TracerProvider

if TYPE_CHECKING:
    from faststream.types import AnyDict


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
        }


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
