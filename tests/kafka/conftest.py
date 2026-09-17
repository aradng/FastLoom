import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from fastloom.observability.settings import ObservabilitySettings
from fastloom.signals.kafka.depends import KafkaSubscriber
from fastloom.signals.kafka.settings import KafkaSettings

# see docs/internal-testing.md#kafka for why this runs at module scope
kafka_span_exporter = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(kafka_span_exporter))
trace.set_tracer_provider(_provider)


class _TracedKafkaSettings(ObservabilitySettings, KafkaSettings): ...


@pytest.fixture
async def kafka_subscriber(kafka_container):
    settings = _TracedKafkaSettings(
        ENVIRONMENT="test",
        PROJECT_NAME="fastloom_test",
        KAFKA_URI=kafka_container.get_bootstrap_server(),
        OTEL_ENABLED=1,
    )
    subscriber = KafkaSubscriber(settings)
    try:
        yield subscriber
    finally:
        await subscriber.router.broker.stop()
        KafkaSubscriber.unbind()


@pytest.fixture
def kafka_spans():
    kafka_span_exporter.clear()
    yield kafka_span_exporter
