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
    # NOTE: publish(None, ...) isn't a real Kafka tombstone - encode_message()
    # turns None into b"", and compaction only reclaims a key on a literal
    # null value (ag2ai/faststream#1967). Patched onto the class, at the same
    # deferred point get_kafka_router() imports from, so every publisher gets
    # .publish_tombstone(key) for free - see docs/signals.md#ordering.
    if hasattr(publisher_cls, "publish_tombstone"):
        return

    async def publish_tombstone(
        self: DefaultPublisher, key: bytes | str
    ) -> None:
        await self._outer_config.producer._producer.producer.send(  # noqa: SLF001
            topic=self.topic, key=key, value=None
        )

    publisher_cls.publish_tombstone = publish_tombstone


class KafkaSubscriber(SelfSustaining):
    """Owns the shared FastStream KafkaRouter singleton."""

    router: KafkaRouter

    def __init__(self, settings: KafkaSubscriptable):
        super().__init__()
        self.router = get_kafka_router(settings)
