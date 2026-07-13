from __future__ import annotations

from typing import TYPE_CHECKING

from fastloom.meta import SelfSustaining
from fastloom.signals.kafka.settings import KafkaSettings, KafkaSubscriptable

if TYPE_CHECKING:
    from faststream.confluent.fastapi import KafkaRouter


def get_kafka_router(settings: KafkaSettings) -> KafkaRouter:
    # deferred: see docs/signals.md#ordering
    from faststream.confluent.fastapi import KafkaRouter

    return KafkaRouter(
        settings.KAFKA_URI,
        schema_url="/kafkaapi",
    )


class KafkaSubscriber(SelfSustaining):
    """Owns the shared FastStream KafkaRouter singleton."""

    router: KafkaRouter

    def __init__(self, settings: KafkaSubscriptable):
        super().__init__()
        self.router = get_kafka_router(settings)


async def publish_tombstone(
    router: KafkaRouter, topic: str, key: bytes | str
) -> None:
    """Publish a genuine Kafka null-value record (a real tombstone) for a
    compacted-topic delete.

    `publisher.publish(None, ...)` is *not* a tombstone: FastStream's
    `encode_message()` unconditionally turns a `None` body into `b""` before
    it ever reaches the producer (see `faststream.message.utils`), and Kafka
    log compaction only reclaims a key on a literal null value — a
    zero-length-but-present byte string is kept forever as "the current
    value" for that key (see ag2ai/faststream#1967, which fixed *consuming*
    a real tombstone but left producing one unaddressed). This bypasses
    `encode_message` and sends the null straight through the raw producer.
    """
    key_bytes = key.encode() if isinstance(key, str) else key
    raw_producer = router.broker._producer._producer.producer  # noqa: SLF001
    await raw_producer.send(topic=topic, key=key_bytes, value=None)
