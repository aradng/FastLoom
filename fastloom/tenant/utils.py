from typing import Any, Generic, TypeVar

from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo

from fastloom.meta import create_optional_model, optional_fieldinfo

V = TypeVar("V", bound=BaseModel)
U = TypeVar("U", bound=BaseModel)
Z = TypeVar("Z", bound=BaseModel)


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
        self.optional = create_optional_model(
            model, name=f"Optional{model.__name__}", strip=True
        )
        self.config = create_optional_model(
            model, name=f"OptionalConfig{model.__name__}"
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
        fields: dict[str, FieldInfo] = {
            k: optional_fieldinfo(v, strip=True)[1]
            if k in self.config_default
            else v._copy()
            for k, v in self.model.model_fields.items()
        }
        schema_model: BaseModel = create_model(  # type: ignore[call-overload]
            f"{self.model.__name__}Schema",
            **{k: (v.annotation, v) for k, v in fields.items()},
        )
        return schema_model.model_json_schema()
