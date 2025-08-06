# from collections.abc import Callable, Coroutine
# from typing import Any, get_args

# from beanie.operators import Set

# from core_bluprint.file.models import FileReference
# from core_bluprint.file.schema import FileMessage
# from core_bluprint.signals.depends import RabbitSubscriber as RR

# sub = RR.get()


# def init_file_signals(
#     file_ref_cls: type[FileReference],
# ) -> Callable[..., Coroutine[Any, Any, None]]:
#     usages = get_args(file_ref_cls.model_fields["usage"].annotation)

#     @sub.multi_subscriber(
#         [f"file.{usage}.created" for usage in usages], retry_backoff=True
#     )
#     async def file_uploaded(files: list[FileMessage]):
#         for file in files:
#             new_file_ref = file_ref_cls(**file.model_dump(), matched=True)
#             await file_ref_cls.find_one(
#                 file_ref_cls.name == file.name,
#                 file_ref_cls.usage == file.usage,
#                 file_ref_cls.tenant == file.tenant,
#             ).upsert(
#                 Set(new_file_ref.model_dump(exclude={"id"})),
#                 on_insert=new_file_ref,
#             )

#     return file_uploaded
