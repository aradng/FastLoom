from faststream.confluent.fastapi import KafkaRouter

from fastloom.meta import SelfSustaining
from fastloom.signals.settings import KafkaSubscriptable


def get_confluent_router(
    name: str, settings: KafkaSubscriptable
) -> KafkaRouter:
    return KafkaRouter(
        settings.KAFKA_URI,
        schema_url=f"{name}/asyncapi",
    )


class KafkaSubscriber(SelfSustaining):
    """Owns the FastStream KafkaRouter singleton so it can be shared
    across subscriber modules and included in the FastAPI app."""

    router: KafkaRouter

    def __init__(self, settings: KafkaSubscriptable):
        super().__init__()
        self.router = get_confluent_router(settings.API_PREFIX, settings)
