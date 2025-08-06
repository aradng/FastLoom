from collections.abc import Callable, Coroutine
from functools import partial
from typing import Any

from pymongo import AsyncMongoClient


class MongoConnectionError(Exception): ...


async def check_mongo_connection(mongo_uri: str) -> None:
    try:
        client: AsyncMongoClient = AsyncMongoClient(mongo_uri, timeoutms=2000)
        await client.admin.command("ping")
    except Exception as er:
        raise MongoConnectionError(f"MongoDB connection error: {er}") from er


def get_healthcheck(
    mongo_uri: str,
) -> Callable[[], Coroutine[Any, Any, None]]:
    return partial(check_mongo_connection, mongo_uri=mongo_uri)
