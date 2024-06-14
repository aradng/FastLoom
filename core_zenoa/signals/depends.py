import logging
import os

from faststream.confluent import KafkaBroker
from faststream.confluent.fastapi import KafkaRouter
from faststream.rabbit import RabbitBroker
from faststream.rabbit.fastapi import RabbitRouter
from faststream.rabbit.opentelemetry import RabbitTelemetryMiddleware
from opentelemetry import trace

logger = logging.getLogger(__name__)


def _get_kafka_url() -> str:
    return os.getenv("KAFKA_URL", "localhost:9092")


def _get_rabbit_url():
    return os.getenv("RABBIT_URL", "amqp://localhost:5672/")


def get_stream_broker(name: str, kafka_url: str | None = None) -> KafkaBroker:
    kafka_url = kafka_url or _get_kafka_url()
    broker = KafkaBroker(kafka_url)
    logger.debug(f"Created stream broker: {name}: {broker}")
    return broker


def get_stream_router(name: str, kafka_url: str | None = None) -> KafkaRouter:
    kafka_url = kafka_url or _get_kafka_url()
    router = KafkaRouter(kafka_url, schema_url=f"/{name}/asyncapi")
    logger.debug(f"Created stream router: {name}: {router}")
    return router


def get_rabbit_broker(
    name: str, rabbit_url: str | None = None
) -> RabbitBroker:
    rabbit_url = rabbit_url or _get_rabbit_url()
    broker = RabbitBroker(
        rabbit_url,
        schema_url=f"/{name}/asyncapi",
        middlewares=(
            RabbitTelemetryMiddleware(
                tracer_provider=trace.get_tracer_provider()
            ),
        ),
    )
    logger.debug(f"Created stream broker: {name}: {broker}")
    return broker


def get_rabbit_router(
    name: str, rabbit_url: str | None = None
) -> RabbitRouter:
    rabbit_url = rabbit_url or _get_rabbit_url()
    router = RabbitRouter(
        rabbit_url,
        schema_url=f"/{name}/asyncapi",
        middlewares=(
            RabbitTelemetryMiddleware(
                tracer_provider=trace.get_tracer_provider()
            ),
        ),
    )
    logger.debug(f"Created stream router: {name}: {router}")
    return router
