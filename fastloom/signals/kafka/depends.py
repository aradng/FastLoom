from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastloom.meta import SelfSustaining
from fastloom.signals.kafka.settings import KafkaSettings, KafkaSubscriptable

if TYPE_CHECKING:
    from faststream.confluent.fastapi import KafkaRouter


def get_kafka_router(name: str, settings: KafkaSettings) -> KafkaRouter:
    # deferred: see docs/signals.md#ordering
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

    # NOTE: can't subclass KafkaRouter directly — SelfSustainingMeta only
    # proxies attributes that are otherwise *missing* on the class (via
    # __getattr__), so any name KafkaRouter defines (subscriber, publisher,
    # broker, ...) would resolve through normal MRO lookup as the raw
    # unbound method, permanently bypassing the singleton and breaking at
    # call time. These forward explicitly instead, same as RabbitSubscriber.
    @classmethod
    def subscriber(cls, *topics: str, **kwargs: Any):
        return cls.router.subscriber(*topics, **kwargs)

    @classmethod
    def publisher(cls, topic: str, **kwargs: Any):
        return cls.router.publisher(topic, **kwargs)
