from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo

from fastloom.cache.base import BaseTenantSettingCache

if TYPE_CHECKING:
    from fastloom.db.schemas import BaseTenantSettingsDocument
else:
    try:
        from fastloom.db.schemas import BaseTenantSettingsDocument
    except ImportError:
        from pydantic import BaseModel as BaseTenantSettingsDocument


from fastloom.meta import create_optional_model, optional_fieldinfo


class SettingCacheSchema[V: BaseModel]:
    model: type[V]
    config: type[V]
    optional: type[V]
    document: type[BaseTenantSettingsDocument]
    cache: type[BaseTenantSettingCache]
    config_default: dict[str, Any] = {}

    def __init__(
        self,
        model: type[V],
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
                BaseTenantSettingsDocument,
            ),
        )
        self.cache = create_model(
            f"{model.__name__}Cache",
            __base__=(  # type: ignore[arg-type]
                self.optional,
                BaseTenantSettingCache,
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
