from collections.abc import MutableMapping
from pathlib import Path
from typing import Annotated, Any, Generic, TypeVar

import yaml
from pydantic import BaseModel, RootModel, StringConstraints

from core_bluprint.auth.introspect.depends import (
    OptionalVerifiedAuth,
    VerifiedAuth,
)
from core_bluprint.tenant.depends import (
    ContextSource,
    HeaderSource,
    OptionalTokenHeaderSource,
    PathSource,
    TenantDependancySelector,
    TokenBodySource,
    TokenHeaderSource,
)
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
    settings_cls: type[T]

    @classmethod
    def load(
        cls, settings_cls: type[T], config_path: Path | None = None
    ) -> None:
        cls.settings = load_settings(settings_cls, config_path)
        cls.settings_cls = settings_cls

    @classmethod
    def get(cls, tenant: str) -> T:
        return cls.settings[tenant]

    @classmethod
    def general(cls) -> T:
        return next(iter(cls.settings.values()))

    @classmethod
    def from_(cls) -> TenantDependancySelector[T]:
        return TenantDependancySelector[cls.settings_cls](  # type: ignore[name-defined]  # noqa: E501
            lambda: load_settings(cls.settings_cls),
            (
                TokenHeaderSource,
                PathSource,
                HeaderSource,
                ContextSource,
                TokenBodySource,
                OptionalTokenHeaderSource,
            ),
        )

    @classmethod
    def auth(cls) -> VerifiedAuth:
        return VerifiedAuth(cls.general())  # type: ignore[arg-type]

    @classmethod
    def optional_auth(cls) -> OptionalVerifiedAuth:
        return OptionalVerifiedAuth(cls.general())  # type: ignore[arg-type]

    def __init__(
        self, settings_cls: type[T], config_path: Path | None = None
    ) -> None:
        self.settings = load_settings(settings_cls, config_path)
