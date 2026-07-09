import pytest

from fastloom.signals.settings import KafkaSubscriptable

pytest_plugins = ["fastloom.test.fixtures.docker"]


@pytest.fixture
async def kafka_subscriber(kafka_container):
    from fastloom.signals.kafka_depends import KafkaSubscriber

    settings = KafkaSubscriptable(
        ENVIRONMENT="test",
        PROJECT_NAME="fastloom_test",
        KAFKA_URI=kafka_container.get_bootstrap_server(),
    )
    subscriber = KafkaSubscriber(settings)
    await subscriber.router.broker.start()
    try:
        yield subscriber
    finally:
        await subscriber.router.broker.stop()
        KafkaSubscriber.self = None
