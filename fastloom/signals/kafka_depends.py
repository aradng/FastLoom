from faststream.confluent.fastapi import KafkaRouter

from fastloom.meta import SelfSustaining
from fastloom.signals.settings import KafkaSettings, KafkaSubscriptable


def get_kafka_router(name: str, settings: KafkaSettings) -> KafkaRouter:
    return KafkaRouter(
        settings.KAFKA_URI,
        schema_url=f"{name}/asyncapi",
    )


class KafkaSubscriber(SelfSustaining):
    """Owns the shared FastStream KafkaRouter singleton."""

    router: KafkaRouter

    def __init__(self, settings: KafkaSubscriptable):
        super().__init__()
        self.router = get_kafka_router(settings.API_PREFIX, settings)
