from beanie import PydanticObjectId

from fastloom.file.models import FileReference
from fastloom.file.schema import FileIn


async def get_or_create_reference(
    file_ref_cls: type[FileReference], file_in: FileIn, tenant: str
) -> FileReference | None:
    if file_in is None:
        return None
    return await file_ref_cls.find_one(
        file_ref_cls.name == file_in.name, file_ref_cls.tenant == tenant
    ) or file_ref_cls(  # type: ignore[call-arg]
        id=PydanticObjectId(),
        name=file_in.name,
        matched=False,
        tenant=tenant,  # TODO: wtf is wrong with providing tenant? mypy blames
    )
