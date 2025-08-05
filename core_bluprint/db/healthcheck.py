from pymongo import AsyncMongoClient


class MongoConnectionError(Exception): ...


async def check_mongo_connection(mongo_uri: str) -> None:
    try:
        client: AsyncMongoClient = AsyncMongoClient(mongo_uri, timeoutms=2000)
        await client.server_info()
        await client["test"]["test"].find().to_list(length=1)
    except Exception as er:
        raise MongoConnectionError(f"MongoDB connection error: {er}") from er
