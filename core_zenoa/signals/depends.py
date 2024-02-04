import logging
import os

from faststream.kafka import KafkaBroker
from faststream.kafka.fastapi import KafkaRouter

logger = logging.getLogger(__name__)


def _get_kafka_url() -> str:
    return os.getenv("KAFKA_URL", "localhost:9092")


def get_stream_broker(name: str, kafka_url: str | None = None) -> KafkaBroker:
    kafka_url = kafka_url or _get_kafka_url()
    broker = KafkaBroker(kafka_url)
    logger.debug(f"Created stream broker: {name}: {broker}")
    return broker


def get_stream_router(name: str, kafka_url: str | None = None) -> KafkaRouter:
    kafka_url = kafka_url or _get_kafka_url()
    router = KafkaRouter(kafka_url, schema_url=f"/asyncapi/{name}")
    logger.debug(f"Created stream router: {name}: {router}")
    return router
