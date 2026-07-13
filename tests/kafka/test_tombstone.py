import asyncio
from typing import cast

from confluent_kafka import Message
from faststream.confluent.fastapi import KafkaMessage


async def test_publish_none_sends_a_real_null_value(kafka_subscriber):
    router = kafka_subscriber.router
    values: list[bytes | None] = []
    received = asyncio.Event()

    @router.subscriber(
        "tombstone-test-topic",
        group_id="tombstone-test",
        auto_offset_reset="earliest",
    )
    async def handler(msg: KafkaMessage) -> None:
        rec = cast(Message, msg.raw_message)
        values.append(rec.value())
        if len(values) == 2:
            received.set()

    publisher = router.publisher("tombstone-test-topic")
    await router.broker.start()
    try:
        await publisher.publish("hello", key=b"regular-message")
        await publisher.publish(None, key=b"real-delete")
        await asyncio.wait_for(received.wait(), timeout=15)
    finally:
        await router.broker.stop()

    regular_value, tombstone_value = values
    assert regular_value == b"hello"
    assert tombstone_value is None
