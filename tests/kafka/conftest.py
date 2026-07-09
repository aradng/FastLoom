import pytest
from opentelemetry.instrumentation.confluent_kafka import (
    ConfluentKafkaInstrumentor,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from fastloom.signals.kafka.depends import KafkaSubscriber
from fastloom.signals.kafka.settings import KafkaSubscriptable

# see docs/internal-testing.md#kafka for why this runs at module scope
kafka_span_exporter = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(kafka_span_exporter))
ConfluentKafkaInstrumentor().instrument(tracer_provider=_provider)


@pytest.fixture
async def kafka_subscriber(kafka_container):
    settings = KafkaSubscriptable(
        ENVIRONMENT="test",
        PROJECT_NAME="fastloom_test",
        KAFKA_URI=kafka_container.get_bootstrap_server(),
    )
    subscriber = KafkaSubscriber(settings)
    try:
        yield subscriber
    finally:
        await subscriber.router.broker.stop()
        KafkaSubscriber.self = None


@pytest.fixture
def kafka_spans():
    kafka_span_exporter.clear()
    yield kafka_span_exporter
