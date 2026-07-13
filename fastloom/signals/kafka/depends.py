from __future__ import annotations

from typing import TYPE_CHECKING

from fastloom.meta import SelfSustaining
from fastloom.signals.kafka.settings import KafkaSettings, KafkaSubscriptable

if TYPE_CHECKING:
    from faststream.confluent.fastapi import KafkaRouter
    from faststream.confluent.publisher.usecase import DefaultPublisher


def get_kafka_router(settings: KafkaSettings) -> KafkaRouter:
    # deferred: see docs/signals.md#ordering
    from faststream.confluent.fastapi import KafkaRouter
    from faststream.confluent.publisher.usecase import DefaultPublisher

    _patch_publish_tombstone(DefaultPublisher)

    return KafkaRouter(
        settings.KAFKA_URI,
        schema_url="/kafkaapi",
    )


def _patch_publish_tombstone(publisher_cls: type[DefaultPublisher]) -> None:
    """Give every `router.publisher(...)` instance a `.publish_tombstone(key)`.

    `publisher.publish(None, ...)` is *not* a Kafka tombstone: FastStream's
    `encode_message()` unconditionally turns a `None` body into `b""` before
    it ever reaches the producer (see `faststream.message.utils`), and Kafka
    log compaction only reclaims a key on a literal null value — a
    zero-length-but-present byte string is kept forever as "the current
    value" for that key (see ag2ai/faststream#1967, which fixed *consuming*
    a real tombstone but left producing one unaddressed). `publish_tombstone`
    bypasses `encode_message` and sends the null straight through the raw
    producer. Patched onto the class rather than exposed as a standalone
    helper so every publisher gets it without touching its construction
    call sites - the same monkey-patch shape `ConfluentKafkaInstrumentor`
    already uses on `confluent_kafka.Producer` (see docs/signals.md#ordering).
    """
    if hasattr(publisher_cls, "publish_tombstone"):
        return

    async def publish_tombstone(
        self: DefaultPublisher, key: bytes | str
    ) -> None:
        key_bytes = key.encode() if isinstance(key, str) else key
        raw_producer = self._outer_config.producer._producer.producer  # noqa: SLF001
        await raw_producer.send(topic=self.topic, key=key_bytes, value=None)

    publisher_cls.publish_tombstone = publish_tombstone


class KafkaSubscriber(SelfSustaining):
    """Owns the shared FastStream KafkaRouter singleton."""

    router: KafkaRouter

    def __init__(self, settings: KafkaSubscriptable):
        super().__init__()
        self.router = get_kafka_router(settings)
