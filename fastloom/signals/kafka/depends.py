from __future__ import annotations

from typing import TYPE_CHECKING

from fastloom.meta import SelfSustaining
from fastloom.signals.kafka.settings import KafkaSettings, KafkaSubscriptable

if TYPE_CHECKING:
    from faststream.confluent.fastapi import KafkaRouter


def get_kafka_router(name: str, settings: KafkaSettings) -> KafkaRouter:
    # deferred: see docs/signals.md#ordering-is-reversed-from-rabbit
    from faststream.confluent.fastapi import KafkaRouter

    return KafkaRouter(
        settings.KAFKA_URI,
        schema_url=f"{name}/kafkaapi",
    )


class KafkaSubscriber(SelfSustaining):
    """Owns the shared FastStream KafkaRouter singleton."""

    router: KafkaRouter

    def __init__(self, settings: KafkaSubscriptable):
        super().__init__()
        self.router = get_kafka_router(settings.API_PREFIX, settings)
