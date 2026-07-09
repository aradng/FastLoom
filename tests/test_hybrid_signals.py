from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastloom.signals.depends import get_rabbit_router
from fastloom.signals.kafka.depends import get_kafka_router
from fastloom.signals.kafka.settings import KafkaSettings
from fastloom.signals.settings import RabbitmqSettings


def _mock_broker(router):
    router.broker.start = AsyncMock()
    router.broker.stop = AsyncMock()
    return router


async def test_rabbit_and_kafka_asyncapi_docs_do_not_collide():
    name = "/api/hybrid-test"
    rabbit_router = _mock_broker(
        get_rabbit_router(
            name,
            RabbitmqSettings(RABBIT_URI="amqp://guest:guest@localhost:5672/"),
        )
    )
    kafka_router = _mock_broker(
        get_kafka_router(name, KafkaSettings(KAFKA_URI="localhost:9092"))
    )

    app = FastAPI()
    app.include_router(rabbit_router)
    app.include_router(kafka_router)

    with TestClient(app) as client:
        rabbit_schema = client.get(f"{name}/rabbitapi.json").json()
        kafka_schema = client.get(f"{name}/kafkaapi.json").json()

    assert rabbit_schema["servers"]["development"]["protocol"] == "amqp"
    assert kafka_schema["servers"]["development"]["protocol"] == "kafka"

    docs_paths = [
        route.path
        for route in app.routes
        if route.path.startswith(f"{name}/rabbitapi")
        or route.path.startswith(f"{name}/kafkaapi")
    ]
    assert len(docs_paths) == len(set(docs_paths)), (
        "Rabbit and Kafka registered a route at the same path — one is "
        "silently shadowing the other."
    )
