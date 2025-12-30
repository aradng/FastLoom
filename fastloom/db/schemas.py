from datetime import datetime
from typing import TYPE_CHECKING, Annotated

if TYPE_CHECKING:
    from beanie import (
        Document,
        Indexed,
        Insert,
        Replace,
        SaveChanges,
        Update,
        before_event,
    )
else:
    try:
        from beanie import (
            Document,
            Indexed,
            Insert,
            Replace,
            SaveChanges,
            Update,
            before_event,
        )
    except ImportError:
        from pydantic import BaseModel as Document
        from pydantic import BaseModel as Insert
        from pydantic import BaseModel as Replace
        from pydantic import BaseModel as SaveChanges
        from pydantic import BaseModel as Update

        def Indexed() -> type:
            return str

        def before_event(*args, **kwargs):
            def decorator(func):
                return func

            return decorator


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
