import functools
from collections.abc import Awaitable, Callable

from pymongo import AsyncMongoClient
from pymongo.asynchronous.client_session import AsyncClientSession

from fastloom.db.lifehooks import get_mongo_client


class MongoTransactionManager:
    def __init__(self, mongo_uri: str):
        self.mongo_uri = mongo_uri

    async def __aenter__(self) -> AsyncClientSession:
        self.client: AsyncMongoClient = await get_mongo_client(self.mongo_uri)
        self.session: AsyncClientSession = self.client.start_session()
        await self.session.start_transaction()
        return self.session

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_val: BaseException | None = None,
        exc_tb: object | None = None,
    ):
        if exc_type:
            await self.session.abort_transaction()
        else:
            await self.session.commit_transaction()
        await self.session.end_session()
        await self.client.close()


def with_transaction[T, **P](
    mongo_uri: str,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    def transaction_wrapper(
        func: Callable[P, Awaitable[T]],
    ) -> Callable[P, Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            async with MongoTransactionManager(mongo_uri) as session:
                kwargs["session"] = session
                return await func(*args, **kwargs)

        return wrapper

    return transaction_wrapper
