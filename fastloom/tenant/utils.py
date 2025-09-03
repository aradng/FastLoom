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
        # field.annotation = field.annotation | None
    return field


# [settings class , document class, cache class]
class SettingCacheSchema(Generic[V, U, Z]):
    model: type[V]
    config: type[BaseModel]
    optional: type[BaseModel]
    document: type[U]
    cache: type[Z]
    config_default: dict[str, Any] = {}

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

    def strip_defaults(self, fetched: V) -> dict[str, Any]:
        stripped = fetched.model_dump(exclude_defaults=True)
        for key in self.config_default:
            if key in stripped and stripped[key] == self.config_default[key]:
                del stripped[key]

        return stripped

    def get_schema(self) -> dict[str, Any]:
        fields: dict[str, FieldInfo] = {}
        for k, v in self.model.model_fields.items():
            if k in self.config_default:
                fields[k] = config_default(v, strip=True)
                fields[k].annotation = v.annotation | None  # type:ignore[assignment, operator]
            else:
                fields[k] = v._copy()
        schema_model: BaseModel = create_model(  # type: ignore[call-overload]
            f"{self.model.__name__}Schema",
            **{k: (v.annotation, v) for k, v in fields.items()},
        )
        return schema_model.model_json_schema()
