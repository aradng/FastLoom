"""ConfluentKafkaInstrumentor patches confluent_kafka.Producer/Consumer at
import time; FastStream's confluent client binds those names via
`from confluent_kafka import Producer`, so instrumentation must run before
faststream.confluent is ever imported in the process. Any other test that
imports fastloom.signals.kafka_depends first would poison that for the rest
of the session, so this runs in a fresh subprocess instead of in-process.
"""

import asyncio
import json
import sys
import textwrap

SUBPROCESS_SCRIPT = textwrap.dedent("""
    import asyncio
    import json
    import sys

    from opentelemetry.instrumentation.confluent_kafka import (
        ConfluentKafkaInstrumentor,
    )
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    ConfluentKafkaInstrumentor().instrument(tracer_provider=provider)

    from fastloom.signals.kafka_depends import KafkaSubscriber
    from fastloom.signals.settings import KafkaSubscriptable


    async def main(bootstrap_server: str, topic: str) -> list[str]:
        settings = KafkaSubscriptable(
            ENVIRONMENT="test",
            PROJECT_NAME="fastloom_test",
            KAFKA_URI=bootstrap_server,
        )
        KafkaSubscriber(settings)
        router = KafkaSubscriber.router
        received = asyncio.Event()

        @router.subscriber(
            topic, group_id="otel-test", auto_offset_reset="earliest"
        )
        async def handler(_: dict) -> None:
            received.set()

        publisher = router.publisher(topic)
        await router.broker.start()
        try:
            await publisher.publish({"hello": "world"})
            await asyncio.wait_for(received.wait(), timeout=15)
        finally:
            await router.broker.stop()

        return [span.name for span in exporter.get_finished_spans()]


    if __name__ == "__main__":
        span_names = asyncio.run(main(sys.argv[1], sys.argv[2]))
        print(json.dumps(span_names))
""")


async def test_kafka_produce_consume_emits_otel_spans(kafka_container):
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        SUBPROCESS_SCRIPT,
        kafka_container.get_bootstrap_server(),
        "otel-test-topic",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    assert proc.returncode == 0, stderr.decode()

    span_names = json.loads(stdout.decode().strip().splitlines()[-1])
    # "recv" spans come from confluent_kafka.Consumer.poll(), which polls
    # repeatedly while idle — count is non-deterministic, so only assert
    # on the spans tied to the one message actually sent.
    assert "otel-test-topic send" in span_names
    assert "otel-test-topic process" in span_names
    assert "recv" in span_names
