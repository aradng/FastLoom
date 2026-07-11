import pytest

from fastloom.signals.kafka.depends import get_kafka_router
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


async def test_kafka_healthcheck_fails_against_dead_broker():
    settings = KafkaSubscriptable(
        ENVIRONMENT="test",
        PROJECT_NAME="fastloom_test",
        KAFKA_URI="localhost:1",
    )
    router = get_kafka_router(settings)
    try:
        # ping() on an unstarted router short-circuits to False
        await router.broker.start()
        with pytest.raises(KafkaConnectionError):
            await get_healthcheck(router)()
    finally:
        await router.broker.stop()
