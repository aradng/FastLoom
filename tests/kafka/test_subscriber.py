import asyncio

import pytest

from fastloom.signals.kafka.depends import KafkaSubscriber, get_kafka_router
from fastloom.signals.kafka.healthcheck import (
    KafkaConnectionError,
    get_healthcheck,
)
from fastloom.signals.kafka.settings import KafkaSubscriptable


async def test_kafka_healthcheck_ok(kafka_subscriber):
    router = kafka_subscriber.router
    await router.broker.start()
    try:
        await get_healthcheck(router)()
    finally:
        await router.broker.stop()


async def test_kafka_subscriber_classmethods_forward_to_router(
    kafka_subscriber,
):
    received = asyncio.Event()

    @KafkaSubscriber.subscriber(
        "classmethod-test-topic",
        group_id="classmethod-test",
        auto_offset_reset="earliest",
    )
    async def handler(_: dict) -> None:
        received.set()

    publisher = KafkaSubscriber.publisher("classmethod-test-topic")
    await kafka_subscriber.router.broker.start()
    try:
        await publisher.publish({"hello": "world"})
        await asyncio.wait_for(received.wait(), timeout=15)
    finally:
        await kafka_subscriber.router.broker.stop()

    assert received.is_set()


async def test_kafka_healthcheck_fails_against_dead_broker():
    settings = KafkaSubscriptable(
        ENVIRONMENT="test",
        PROJECT_NAME="fastloom_test",
        KAFKA_URI="localhost:1",
    )
    router = get_kafka_router(settings.API_PREFIX, settings)
    try:
        # ping() on an unstarted router short-circuits to False
        await router.broker.start()
        with pytest.raises(KafkaConnectionError):
            await get_healthcheck(router)()
    finally:
        await router.broker.stop()
