from datetime import datetime
from functools import cache
from typing import (
    TYPE_CHECKING,
    Annotated,
    Generic,
    Literal,
    TypeAliasType,
    get_args,
)

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


from pydantic import (
    BaseModel,
    Field,
    GetCoreSchemaHandler,
    computed_field,
    create_model,
)
from pydantic_core import CoreSchema
from typing_extensions import TypeVar

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


MaxLimit = TypeVar("MaxLimit", bound=int, default=Literal[100])
DefaultLimit = TypeVar("DefaultLimit", bound=int, default=Literal[10])

if TYPE_CHECKING:
    PageLimit = TypeAliasType(  # noqa: UP040
        "PageLimit", int, type_params=(MaxLimit,)
    )
else:

    class PageLimit:
        def __class_getitem__(cls, max_size):
            return Annotated[int, Field(ge=1, le=get_args(max_size)[0])]

        @classmethod
        def __get_pydantic_core_schema__(
            cls, source: type, handler: GetCoreSchemaHandler
        ) -> CoreSchema:
            return handler.generate_schema(cls[Literal[100]])


PageOffset = Annotated[int, Field(ge=0)]


class BasePaginationQuery(BaseModel, Generic[MaxLimit, DefaultLimit]):
    offset: PageOffset = 0
    limit: PageLimit = 10

    if not TYPE_CHECKING:

        @classmethod
        @cache
        def __class_getitem__(cls, limits):
            max_size, default = (get_args(lit)[0] for lit in limits)
            if not 1 <= default <= max_size:
                raise ValueError(f"default {default} outside 1..{max_size}")
            return create_model(
                f"{cls.__name__}[{max_size}, {default}]",
                __base__=cls,
                limit=(PageLimit[Literal[max_size]], default),
            )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def skip(self) -> int:
        return self.limit * self.offset


class PaginatedResponse[T](BaseModel):
    data: list[T] = Field(default_factory=list)
    count: int = Field(default=0, ge=0)


class BaseTenantSettingsDocument(CreatedUpdatedAtSchema, Document):
    id: Annotated[str, Indexed()]  # type: ignore[assignment]

    class Settings:
        name = "settings"
