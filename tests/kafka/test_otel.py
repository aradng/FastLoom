import asyncio


async def test_kafka_produce_consume_emits_otel_spans(
    kafka_subscriber, kafka_spans
):
    router = kafka_subscriber.router
    received = asyncio.Event()

    @router.subscriber(
        "otel-test-topic", group_id="otel-test", auto_offset_reset="earliest"
    )
    async def handler(_: dict) -> None:
        received.set()

    publisher = router.publisher("otel-test-topic")
    await router.broker.start()
    try:
        await publisher.publish({"hello": "world"})
        await asyncio.wait_for(received.wait(), timeout=15)
    finally:
        await router.broker.stop()

    span_names = [span.name for span in kafka_spans.get_finished_spans()]
    assert "otel-test-topic send" in span_names
    assert "otel-test-topic process" in span_names
