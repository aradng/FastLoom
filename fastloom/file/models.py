from enum import StrEnum

from beanie import Document
from pydantic import model_validator
from pymongo import IndexModel

from fastloom.db.schemas import CreatedUpdatedAtSchema
from fastloom.file.schema import (
    BaseFile,
    FileMetaData,
    RequiredMediaPath,
)
from fastloom.tenant.schemas import TenantMixin


class FileObject(Document, TenantMixin):
    class Settings:
        name = "files"
        indexes = [IndexModel(["name", "tenant"], unique=True)]

    name: str
    usage: StrEnum
    metadata: FileMetaData
    content_type: str
    path: RequiredMediaPath


class FileReference(Document, TenantMixin, BaseFile, CreatedUpdatedAtSchema):
    class Settings:
        name = "file_references"
        indexes = [
            IndexModel(
                ["created_at"],
                expireAfterSeconds=60 * 60 * 24 * 7,  # 7 days
                partialFilterExpression=dict(matched=False),
                name="expire_after_7_days",
            ),
        ]

    usage: StrEnum

    @model_validator(mode="after")
    def validate_content_length_and_matched(self):
        if self.matched and self.content_length is None:
            self.content_length = -1
        return self
