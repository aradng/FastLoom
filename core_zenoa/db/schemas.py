from datetime import datetime

import bson
from beanie import (
    Document,
    Insert,
    PydanticObjectId,
    Replace,
    SaveChanges,
    Update,
    before_event,
)
from pydantic import BaseModel, Field

from core_zenoa.date import utcnow


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
    id: PydanticObjectId = Field(default_factory=bson.ObjectId, alias="_id")  # type: ignore[assignment] # noqa
