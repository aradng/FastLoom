import asyncio

from beanie import Document, init_beanie
from motor.core import AgnosticClient
from motor.motor_asyncio import AsyncIOMotorClient


async def init_db(
    database_name: str,
    models: list[Document],
    mongo_uri: str,
):
    client: AgnosticClient = AsyncIOMotorClient(mongo_uri, tz_aware=True)
    client.get_io_loop = asyncio.get_event_loop  # type: ignore[method-assign]
    db = client[database_name]
    await init_beanie(db, document_models=models)  # type: ignore[arg-type]


async def destroy_db(
    database_name: str,
    models: list[Document],
    mongo_uri: str,
    drop_database: bool = False,
):
    client: AgnosticClient = AsyncIOMotorClient(mongo_uri)
    client.get_io_loop = asyncio.get_event_loop  # type: ignore[method-assign]
    db = client[database_name]
    if not drop_database:
        for model in models[1:]:  # Skip pre-populated Province collection
            await db.drop_collection(model.Settings.name)
    else:
        await client.drop_database(database_name)
