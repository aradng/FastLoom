import pytest

from fastloom.signals.kafka_healthcheck import (
    KafkaConnectionError,
    get_healthcheck,
)


async def test_kafka_healthcheck_ok(kafka_subscriber):
    router = kafka_subscriber.router
    await router.broker.start()
    try:
        await get_healthcheck(router)()
    finally:
        await router.broker.stop()


async def test_kafka_healthcheck_fails_against_dead_broker():
    from fastloom.signals.kafka_depends import get_kafka_router
    from fastloom.signals.settings import KafkaSubscriptable

    settings = KafkaSubscriptable(
        ENVIRONMENT="test",
        PROJECT_NAME="fastloom_test",
        KAFKA_URI="localhost:1",
    )
    router = get_kafka_router(settings.API_PREFIX, settings)
    try:
        # start() must run first: an unstarted router's ping() short-circuits
        # via "if not producer: return False" before ever touching the
        # network, which would pass this test for the wrong reason.
        await router.broker.start()
        with pytest.raises(KafkaConnectionError):
            await get_healthcheck(router)()
    finally:
        await router.broker.stop()
