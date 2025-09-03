import json
from collections.abc import Generator
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    PlainSerializer,
    model_validator,
)

from fastloom.types import NoneField


def _file_to_path(
    file: "str | dict[str, Any] | RequiredMediaPath | OptionalFileField",
) -> "MediaPath":
    if file is None:
        return None

    if isinstance(file, str):
        return RequiredMediaPath(file)

    if isinstance(file, Path):
        return file

    if isinstance(file, dict):
        return _file_to_path(file.get("path"))

    return file.path if file.path else file.name


# TODO remove when FE is compatible
MediaPath = Annotated[
    Path | str | None,
    BeforeValidator(_file_to_path),
    PlainSerializer(lambda p: str(p) if p else None, return_type=str | None),
]
RequiredMediaPath = Annotated[Path, PlainSerializer(str, return_type=str)]


class FileMetaData(BaseModel):
    user_id: str
    username: str


class Filename(BaseModel):
    name: str


class FileContentData(BaseModel):
    content_type: str | None = None
    content_length: int | None = None


class FileMessage(Filename, FileContentData):
    name: str
    usage: StrEnum
    metadata: FileMetaData
    path: RequiredMediaPath
    tenant: str = Field(validation_alias="bucket")


FileIn = Annotated[Filename | None, Field(None)]


class BaseFile(Filename, FileContentData):
    path: MediaPath = None
    matched: bool

    @model_validator(mode="after")
    def validate_content_length_and_matched(self):
        assert (
            (self.path is None)
            == (self.content_type is None)
            == (self.content_length is None)
            == (not self.matched)
        ), json.dumps(
            {
                "path": str(self.path),
                "content_type": self.content_type,
                "content_length": self.content_length,
                "matched": self.matched,
            }
        )
        return self


class UnmatchedFile(BaseFile):
    path: NoneField = None
    content_type: NoneField = None
    content_length: NoneField = None
    matched: Literal[False] = False


class MatchedFile(BaseFile):
    path: RequiredMediaPath = Field(default_factory=Path)
    content_type: str = Field(default_factory=str)
    content_length: int = -1
    matched: Literal[True] = True


FileField = Annotated[
    MatchedFile | UnmatchedFile, Field(union_mode="left_to_right")
]

OptionalFileField = Annotated[FileField | None, Field(None)]

FileFind: TypeAlias = Generator[FileField, Any, None]
