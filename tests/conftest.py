import pytest
from opentelemetry.instrumentation.confluent_kafka import (
    ConfluentKafkaInstrumentor,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from fastloom.signals.settings import KafkaSubscriptable

pytest_plugins = ["fastloom.test.fixtures.docker"]

# ConfluentKafkaInstrumentor patches confluent_kafka.Producer/Consumer at
# the class level, and FastStream's confluent client binds those names via
# `from confluent_kafka import Producer` at import time — so this has to
# run before anything in this session imports fastloom.signals.kafka_depends
# (deferred to fixture/test bodies below) or instrumentation is permanently
# a no-op for the rest of the process.
kafka_span_exporter = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(kafka_span_exporter))
ConfluentKafkaInstrumentor().instrument(tracer_provider=_provider)


@pytest.fixture
async def kafka_subscriber(kafka_container):
    from fastloom.signals.kafka_depends import KafkaSubscriber

    settings = KafkaSubscriptable(
        ENVIRONMENT="test",
        PROJECT_NAME="fastloom_test",
        KAFKA_URI=kafka_container.get_bootstrap_server(),
    )
    subscriber = KafkaSubscriber(settings)
    try:
        yield subscriber
    finally:
        KafkaSubscriber.self = None


@pytest.fixture
def kafka_spans():
    kafka_span_exporter.clear()
    yield kafka_span_exporter
