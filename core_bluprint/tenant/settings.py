from collections.abc import MutableMapping
from pathlib import Path
from typing import Annotated, Any, Generic, TypeVar

import yaml
from pydantic import BaseModel, RootModel, StringConstraints

from core_bluprint.tenant.protocols import TenantHostSchema, TenantNameSchema

DEFAULT_CONFIG_KEY: str = "default"


T = TypeVar("T", bound=BaseModel)

TenantName = Annotated[str, StringConstraints(strip_whitespace=True)]
TenantMapping = MutableMapping[TenantName, TenantNameSchema]
TenantMappingWithHosts = MutableMapping[TenantName, TenantHostSchema]


def load_settings(
    settings_cls: type[T], config_yml_file: Path | None = None
) -> MutableMapping[str, T]:
    config_yml_file = config_yml_file or Path.cwd() / "tenants.yaml"
    _loaded_configs: dict[str, Any]
    with config_yml_file.open() as f:
        _loaded_configs = yaml.safe_load(f)

    _default_config: dict[str, Any] = _loaded_configs.pop(
        DEFAULT_CONFIG_KEY, {}
    )
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


class TenantConfigs(Generic[T]):
    settings: MutableMapping[str, T]

    def __init__(
        self, settings_cls: type[T], config_path: Path | None = None
    ) -> None:
        self.settings = load_settings(settings_cls, config_path)
