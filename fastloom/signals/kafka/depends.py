from __future__ import annotations

from typing import TYPE_CHECKING

from fastloom.meta import SelfSustaining
from fastloom.signals.kafka.settings import KafkaSettings, KafkaSubscriptable

if TYPE_CHECKING:
    from faststream.confluent.fastapi import KafkaRouter
    from faststream.confluent.publisher.producer import (
        AsyncConfluentFastProducerImpl,
    )
    from faststream.confluent.response import KafkaPublishCommand


def get_kafka_router(settings: KafkaSettings) -> KafkaRouter:
    # deferred: see docs/signals.md#ordering
    from faststream.confluent.fastapi import KafkaRouter
    from faststream.confluent.publisher.producer import (
        AsyncConfluentFastProducerImpl,
    )

    _patch_real_tombstones(AsyncConfluentFastProducerImpl)

    return KafkaRouter(
        settings.KAFKA_URI,
        schema_url="/kafkaapi",
    )


def _patch_real_tombstones(
    producer_cls: type[AsyncConfluentFastProducerImpl],
) -> None:
    # NOTE: publish(None, ...) isn't a real Kafka tombstone - the codec
    # turns None into b"", and compaction only reclaims a key on a literal
    # null value (ag2ai/faststream#1967). The real fix (ag2ai/faststream#2932)
    # is merged upstream but PyPI rejects packages with direct git/URL
    # dependencies, so we can't just point at git main - keep this shim until
    # faststream cuts an actual PyPI release containing it. Wraps .publish()
    # in place, at the same deferred point get_kafka_router() imports from -
    # see docs/signals.md#ordering.
    if getattr(producer_cls, "_fastloom_real_tombstones", False):
        return

    original_publish = producer_cls.publish

    async def publish(
        self: AsyncConfluentFastProducerImpl, cmd: KafkaPublishCommand
    ):
        if cmd.body is not None:
            return await original_publish(self, cmd)

        headers_to_send = {"content-type": "", **cmd.headers_to_publish()}
        return await self._producer.producer.send(  # noqa: SLF001
            topic=cmd.destination,
            value=None,
            key=cmd.key,
            partition=cmd.partition,
            timestamp_ms=cmd.timestamp_ms,
            headers=[
                (i, (j or "").encode()) for i, j in headers_to_send.items()
            ],
            no_confirm=cmd.no_confirm,
        )

    producer_cls.publish = publish
    producer_cls._fastloom_real_tombstones = True


class KafkaSubscriber(SelfSustaining):
    """Owns the shared FastStream KafkaRouter singleton."""

    router: KafkaRouter

    def __init__(self, settings: KafkaSubscriptable):
        super().__init__()
        self.router = get_kafka_router(settings)
