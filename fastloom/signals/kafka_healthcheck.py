from collections.abc import Callable, Coroutine
from functools import partial
from typing import Any

from faststream.confluent.fastapi import KafkaRouter


class KafkaConnectionError(Exception): ...


async def check_kafka_connection(router: KafkaRouter) -> None:
    if not await router.broker.ping(timeout=5):
        raise KafkaConnectionError("Kafka broker did not respond to ping")


def get_healthcheck(
    router: KafkaRouter,
) -> Callable[[], Coroutine[Any, Any, None]]:
    return partial(check_kafka_connection, router=router)
