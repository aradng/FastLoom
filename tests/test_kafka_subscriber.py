import pytest

from fastloom.signals.kafka_healthcheck import (
    KafkaConnectionError,
    get_healthcheck,
)


async def test_kafka_healthcheck_ok(kafka_subscriber):
    healthcheck = get_healthcheck(kafka_subscriber.router)
    await healthcheck()


async def test_kafka_healthcheck_fails_against_dead_broker():
    from fastloom.signals.kafka_depends import get_confluent_router
    from fastloom.signals.settings import KafkaSubscriptable

    settings = KafkaSubscriptable(
        ENVIRONMENT="test",
        PROJECT_NAME="fastloom_test",
        KAFKA_URI="localhost:1",
    )
    router = get_confluent_router(settings.API_PREFIX, settings)
    healthcheck = get_healthcheck(router)

    with pytest.raises(KafkaConnectionError):
        await healthcheck()
