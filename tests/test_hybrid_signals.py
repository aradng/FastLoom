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


def _flatten_route_paths(routes) -> list[str]:
    # newer FastAPI wraps included routers lazily (no `.path` until
    # `effective_candidates()` resolves them); older FastAPI exposes
    # `.path` directly. Handle both so this doesn't break across upgrades.
    paths = []
    for route in routes:
        if hasattr(route, "effective_candidates"):
            paths.extend(_flatten_route_paths(route.effective_candidates()))
        elif path := getattr(route, "path", None):
            paths.append(path)
    return paths


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
        path
        for path in _flatten_route_paths(app.routes)
        if path.startswith(f"{name}/rabbitapi")
        or path.startswith(f"{name}/kafkaapi")
    ]
    assert len(docs_paths) == len(set(docs_paths)), (
        "Rabbit and Kafka registered a route at the same path — one is "
        "silently shadowing the other."
    )
