from collections.abc import Callable, Coroutine
from typing import Any, get_args

from beanie.operators import Set

from fastloom.file.models import FileReference
from fastloom.file.schema import FileMessage
from fastloom.signals.depends import RabbitSubscriber


def init_file_signals(
    file_ref_cls: type[FileReference],
) -> Callable[..., Coroutine[Any, Any, None]]:
    usages = get_args(file_ref_cls.model_fields["usage"].annotation)

    @RabbitSubscriber.multi_subscriber(
        routing_keys=[f"file.{usage}.created" for usage in usages],
        retry_backoff=True,
    )
    async def file_uploaded(files: list[FileMessage]):
        for file in files:
            new_file_ref = file_ref_cls(**file.model_dump(), matched=True)
            await file_ref_cls.find_one(
                file_ref_cls.name == file.name,
                file_ref_cls.usage == file.usage,
                file_ref_cls.tenant == file.tenant,
            ).upsert(
                Set(new_file_ref.model_dump(exclude={"id"})),
                on_insert=new_file_ref,
            )

    return file_uploaded
