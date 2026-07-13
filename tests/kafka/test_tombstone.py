import asyncio
from typing import cast

from confluent_kafka import Message
from faststream.confluent.fastapi import KafkaMessage
from pydantic import BaseModel


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


class _Foo(BaseModel):
    x: int


async def test_optional_body_param_resolves_to_none_for_tombstone(
    kafka_subscriber,
):
    router = kafka_subscriber.router
    received: list[_Foo | None] = []
    done = asyncio.Event()

    @router.subscriber(
        "consumer-tombstone-test-topic",
        group_id="consumer-tombstone-test",
        auto_offset_reset="earliest",
    )
    async def handler(msg: _Foo | None = None) -> None:
        received.append(msg)
        if len(received) == 2:
            done.set()

    publisher = router.publisher("consumer-tombstone-test-topic")
    await router.broker.start()
    try:
        await publisher.publish({"x": 5}, key=b"regular-message")
        await publisher.publish(None, key=b"real-delete")
        await asyncio.wait_for(done.wait(), timeout=15)
    finally:
        await router.broker.stop()

    assert received == [_Foo(x=5), None]


async def test_optional_body_param_resolves_to_none_for_legacy_empty_value(
    kafka_subscriber,
):
    """A pre-0.4.50 delete is b"" on the wire, not a real null (the original
    tombstone bug) - a fresh `earliest` replay must still resolve it to
    None instead of crash-looping on required fields."""
    router = kafka_subscriber.router
    received: list[_Foo | None] = []
    done = asyncio.Event()

    @router.subscriber(
        "legacy-empty-test-topic",
        group_id="legacy-empty-test",
        auto_offset_reset="earliest",
    )
    async def handler(msg: _Foo | None = None) -> None:
        received.append(msg)
        if len(received) == 2:
            done.set()

    await router.broker.start()
    try:
        raw_producer = router.broker._producer._producer.producer  # noqa: SLF001
        await raw_producer.send(
            topic="legacy-empty-test-topic", key=b"legacy-delete", value=b""
        )
        await router.publisher("legacy-empty-test-topic").publish(
            {"x": 5}, key=b"regular-message"
        )
        await asyncio.wait_for(done.wait(), timeout=15)
    finally:
        await router.broker.stop()

    assert received == [None, _Foo(x=5)]
