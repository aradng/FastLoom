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

    spans = kafka_spans.get_finished_spans()
    names = [span.name for span in spans]
    assert "otel-test-topic publish" in names
    assert "otel-test-topic process" in names


async def test_consumer_joins_the_producer_trace(
    kafka_subscriber, kafka_spans
):
    router = kafka_subscriber.router
    received = asyncio.Event()

    @router.subscriber(
        "otel-join-topic", group_id="otel-join", auto_offset_reset="earliest"
    )
    async def handler(_: dict) -> None:
        received.set()

    publisher = router.publisher("otel-join-topic")
    await router.broker.start()
    try:
        await publisher.publish({"hello": "world"})
        await asyncio.wait_for(received.wait(), timeout=15)
    finally:
        await router.broker.stop()

    spans = kafka_spans.get_finished_spans()
    publish = next(s for s in spans if s.name == "otel-join-topic publish")
    process = next(s for s in spans if s.name == "otel-join-topic process")

    assert process.context.trace_id == publish.context.trace_id
    assert process.parent is not None
