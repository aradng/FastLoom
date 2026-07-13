import asyncio
from typing import cast

from confluent_kafka import Message
from faststream.confluent.fastapi import KafkaMessage


async def test_publish_tombstone_sends_a_real_null_value(kafka_subscriber):
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
        # the existing/naive approach: encode_message() turns None into b""
        await publisher.publish(None, key=b"naive-delete")
        # the fix: a genuine null value on the wire
        await publisher.publish_tombstone(key=b"real-delete")
        await asyncio.wait_for(received.wait(), timeout=15)
    finally:
        await router.broker.stop()

    naive_publish_value, real_tombstone_value = values
    assert naive_publish_value == b""
    assert real_tombstone_value is None
