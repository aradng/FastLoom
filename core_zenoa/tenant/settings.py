from collections.abc import MutableMapping
from pathlib import Path
from typing import Annotated, Any, TypeVar

import yaml
from pydantic import BaseModel, RootModel, StringConstraints

T = TypeVar("T", bound=BaseModel)

TenantName = Annotated[str, StringConstraints(strip_whitespace=True)]

DEFAULT_CONFIG_KEY: str = "default"


def load_settings(
    config_yml_file: Path,
    settings_cls: type[T],
) -> MutableMapping[TenantName, T]:
    loaded_configs: dict[str, Any]
    with config_yml_file.open() as f:
        loaded_configs = yaml.safe_load(f)

    default_config: dict[str, Any] = (
        loaded_configs[DEFAULT_CONFIG_KEY]
        if DEFAULT_CONFIG_KEY in loaded_configs
        else {}
    )

    for tenant, config in loaded_configs.items():
        loaded_configs[tenant] = default_config | (config or {})

    del loaded_configs[DEFAULT_CONFIG_KEY]

    return (
        RootModel[dict[str, settings_cls]]  # type: ignore[valid-type]
        .model_validate(loaded_configs)
        .root
    )
