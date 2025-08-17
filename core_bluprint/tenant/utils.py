import asyncio
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo

V = TypeVar("V", bound=BaseModel)
U = TypeVar("U", bound=BaseModel)
Z = TypeVar("Z", bound=BaseModel)


def config_default(field: FieldInfo, strip: bool = False) -> FieldInfo:
    field = field._copy()
    if field.is_required() or strip:
        field.default = None
        field.default_factory = None
        field.validate_default = False
    return field


# [settings class , document class, cache class]
class SettingCacheSchema(Generic[V, U, Z]):
    model: type[V]
    config: type[BaseModel]
    optional: type[BaseModel]
    document: type[U]
    cache: type[Z]
    config_default: dict[str, Any]

    def __init__(
        self, model: type[V], document_cls: type[U], cache_class: type[Z]
    ):
        self.model = model
        self.optional = create_model(  # type: ignore[assignment, call-overload]
            f"Optional{model.__name__}",
            **{
                k: (
                    v.annotation | None,  # type:ignore[operator]
                    config_default(v, strip=True),
                )
                for k, v in model.model_fields.items()
            },
        )
        self.config = create_model(  # type: ignore[call-overload]
            f"Config{model.__name__}",
            __base__=None,
            **{
                k: (v.annotation | None, config_default(v))  # type:ignore[operator]
                for k, v in model.model_fields.items()
            },
        )
        self.document = create_model(
            f"{model.__name__}Document",
            __base__=(  # type: ignore[arg-type]
                self.optional,
                document_cls,
            ),
        )
        self.cache = create_model(
            f"{model.__name__}Cache",
            __base__=(  # type: ignore[arg-type]
                self.optional,
                cache_class,
            ),
            __cls_kwargs__={"index": True},
        )

    def validate(self, fetched: V) -> V:
        return self.model.model_validate(
            self.config_default | (fetched.model_dump(exclude_defaults=True))
        )


def run_sync(awaitable):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # no event loop running
        return asyncio.run(awaitable)

    if loop.is_running():
        raise RuntimeError("Cannot run inside running loop")
