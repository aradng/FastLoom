import asyncio
from typing import cast

from confluent_kafka import Message
from faststream.confluent.fastapi import KafkaMessage
from pydantic import BaseModel

from fastloom.signals.kafka.depends import TOMBSTONE, Tombstone


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


async def test_typed_body_param_resolves_to_tombstone_sentinel(
    kafka_subscriber,
):
    router = kafka_subscriber.router
    received: list[_Foo | Tombstone] = []
    done = asyncio.Event()

    @router.subscriber(
        "consumer-tombstone-test-topic",
        group_id="consumer-tombstone-test",
        auto_offset_reset="earliest",
    )
    async def handler(msg: _Foo | Tombstone) -> None:
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

    regular, tombstone = received
    assert regular == _Foo(x=5)
    assert tombstone is TOMBSTONE


async def test_optional_body_param_still_resolves_to_plain_none(
    kafka_subscriber,
):
    """A handler that doesn't opt into Tombstone keeps upstream #2933's
    exact Optional[Model] = None behavior - unaffected by the sentinel."""
    router = kafka_subscriber.router
    received: list[_Foo | None] = []
    done = asyncio.Event()

    @router.subscriber(
        "consumer-optional-none-test-topic",
        group_id="consumer-optional-none-test",
        auto_offset_reset="earliest",
    )
    async def handler(msg: _Foo | None = None) -> None:
        received.append(msg)
        if len(received) == 2:
            done.set()

    publisher = router.publisher("consumer-optional-none-test-topic")
    await router.broker.start()
    try:
        await publisher.publish({"x": 5}, key=b"regular-message")
        await publisher.publish(None, key=b"real-delete")
        await asyncio.wait_for(done.wait(), timeout=15)
    finally:
        await router.broker.stop()

    assert received == [_Foo(x=5), None]
