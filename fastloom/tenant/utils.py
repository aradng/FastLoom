from collections.abc import MutableMapping
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Protocol,
    overload,
    runtime_checkable,
)

import yaml
from pydantic import BaseModel, RootModel, create_model
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

DEFAULT_CONFIG_KEY: str = "default"
TENANT_FILE_NAME: str = "tenants.yaml"


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


@runtime_checkable
class ReadableText(Protocol):
    def read(self, size: int = -1) -> str: ...


def load_settings[T: BaseModel](
    settings_cls: type[T],
    config_stream: Path | ReadableText | str | None = None,
    defaults_only: bool = False,
) -> MutableMapping[str, T]:
    config_stream = config_stream or (Path.cwd() / TENANT_FILE_NAME)
    _loaded_configs: dict[str, Any]
    match config_stream:
        case Path():
            with config_stream.open() as f:
                _loaded_configs = yaml.safe_load(f)
        case ReadableText() | str() | bytes():
            _loaded_configs = yaml.safe_load(config_stream)
        case _:
            raise ValueError(
                "config_stream must be a Path or TextIO "
                f"recieved: {type(config_stream)}"
            )

    _default_config: dict[str, Any] = _loaded_configs.pop(
        DEFAULT_CONFIG_KEY, {}
    )
    if defaults_only:
        return {
            DEFAULT_CONFIG_KEY: settings_cls.model_validate(
                _default_config, extra="allow"
            )
        }  # type: ignore[valid-type]
    return (
        RootModel[dict[str, settings_cls]]  # type: ignore[valid-type]
        .model_validate(
            {
                tenant: _default_config | (config or {})
                for tenant, config in _loaded_configs.items()
            }
        )
        .root
    )


@overload
def dump_settings[V: BaseModel, T: BaseModel](
    service_settings: V,
    tenant_settings: MutableMapping[str, T] | None = None,
    yaml_mode: bool = False,
) -> dict[str, Any]: ...


@overload
def dump_settings[V: BaseModel, T: BaseModel](
    service_settings: V,
    tenant_settings: MutableMapping[str, T] | None = None,
    yaml_mode: bool = True,
) -> str: ...


def dump_settings[V: BaseModel, T: BaseModel](
    service_settings: V,
    tenant_settings: MutableMapping[str, T] | None = None,
    yaml_mode: bool = False,
):
    settings_dict = {
        DEFAULT_CONFIG_KEY: service_settings.model_dump(mode="json"),
        **{
            tenant: settings.model_dump(mode="json")
            for tenant, settings in (tenant_settings or {}).items()
        },
    }

    if not yaml_mode:
        return settings_dict
    return yaml.safe_dump(settings_dict, sort_keys=False)
