import pkgutil
from collections.abc import Sequence
from importlib import import_module
from itertools import chain
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from beanie import Document, UnionDoc, View
else:
    try:
        from beanie import Document, UnionDoc, View
    except ImportError:
        from pydantic import (
            BaseModel as Document,
        )
        from pydantic import (
            BaseModel as UnionDoc,
        )
        from pydantic import (
            BaseModel as View,
        )


async def get_mongo_client(mongo_uri: str):
    from pymongo import AsyncMongoClient

    return AsyncMongoClient(
        mongo_uri,
        tz_aware=True,
        connectTimeoutMS=1000,
        serverSelectionTimeoutMS=5000,
    )


def get_models(
    module: ModuleType,
) -> list[type[Document] | type[UnionDoc] | type[View]]:
    if (
        module.__spec__ is None
        or not module.__spec__.submodule_search_locations
    ):
        return [
            x
            for x in vars(module).values()
            if isinstance(x, type)
            and issubclass(x, Document | UnionDoc | View)
            and x not in [Document, UnionDoc, View]
        ]

    return list(
        chain.from_iterable(
            get_models(import_module(f"{module.__name__}.{i.name}"))
            for i in pkgutil.iter_modules(module.__path__)
        )
    )


async def init_db(
    database_name: str,
    models: Sequence[type[Document] | type[UnionDoc] | type[View] | str],
    mongo_uri: str,
):
    from beanie import init_beanie

    client = await get_mongo_client(mongo_uri)
    db = client[database_name]
    await init_beanie(db, document_models=models, recreate_views=True)


async def destroy_db(
    database_name: str,
    models: list[Document],
    mongo_uri: str,
    drop_database: bool = False,
):
    client = await get_mongo_client(mongo_uri)
    db = client[database_name]
    if not drop_database:
        for model in models[1:]:  # Skip pre-populated Province collection
            await db.drop_collection(model.Settings.name)
    else:
        await client.drop_database(database_name)
