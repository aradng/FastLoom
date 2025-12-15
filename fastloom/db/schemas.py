from datetime import datetime
from typing import Annotated, Self

from beanie import (
    Document,
    Indexed,
    Insert,
    PydanticObjectId,
    Replace,
    SaveChanges,
    Update,
    before_event,
)
from fastapi import HTTPException, status
from pydantic import BaseModel, Field, computed_field, field_validator

from fastloom.date import utcnow


class CreatedAtSchema(BaseModel):
    created_at: datetime = Field(default_factory=utcnow)


class CreatedUpdatedAtSchema(CreatedAtSchema):
    """
    ONLY use this mixin in `beanie.Document` models since it uses
    @before_event decorator

    NOTE: `updated_at` doesn't get updated when `update_many` is called
    """

    updated_at: datetime | None = Field(default_factory=utcnow)
    # TODO ^ it shouldn't ideally be None, but some models used to save null
    # so first we have to make sure we cleared db from all such instances

    @before_event(Insert, Replace, SaveChanges, Update)
    async def update_updated_at(self):
        self.updated_at = utcnow()


class BaseDocument(Document):
    @classmethod
    async def get_or_404(cls, id: PydanticObjectId) -> Self:
        obj: Self | None = await cls.get(id)
        if obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{cls.__name__} not found",
            )
        return obj

    @classmethod
    async def find_one_or_404(cls, *args, **kwargs) -> Self:
        obj: Self | None = await cls.find_one(*args, **kwargs)
        if obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{cls.__name__} not found",
            )
        return obj


class BasePaginationQuery(BaseModel):
    offset: int | None = Field(None, ge=0)
    limit: int | None = Field(None, ge=0)

    @field_validator("limit", mode="after")
    @classmethod
    def convert_zero_limit(cls, v: int | None) -> int | None:
        return v or None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def skip(self) -> int | None:
        if self.limit and self.offset is not None:
            return self.limit * self.offset
        return None


class PaginatedResponse[T](BaseModel):
    data: list[T] = Field(default_factory=list)
    count: int = Field(default=0, ge=0)


class BaseTenantSettingsDocument(Document, CreatedUpdatedAtSchema):
    id: Annotated[str, Indexed()]  # type: ignore[assignment]

    class Settings:
        name = "settings"
