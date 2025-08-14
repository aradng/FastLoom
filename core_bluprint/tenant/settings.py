from collections.abc import MutableMapping
from pathlib import Path
from typing import Annotated, Any, Generic, TypeVar

import yaml
from pydantic import BaseModel, RootModel, StringConstraints

from core_bluprint.auth.introspect.depends import (
    OptionalVerifiedAuth,
    VerifiedAuth,
)
from core_bluprint.meta import SelfSustaining
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


class TenantConfigs(Generic[T], SelfSustaining):
    settings: MutableMapping[str, T]
    settings_cls: type[T]
    general: T
    from_: TenantDependancySelector[T]
    auth: VerifiedAuth
    optional_auth: OptionalVerifiedAuth

    def __init__(
        self, settings_cls: type[T], config_path: Path | None = None
    ) -> None:
        super().__init__()
        self.settings = load_settings(settings_cls, config_path)
        self.settings_cls = settings_cls
        self.general = self._general()
        self.from_ = self._from_()
        self.auth = self._auth()
        self.optional_auth = self._optional_auth()

    def _general(self) -> T:
        return next(iter(self.settings.values()))

    def _from_(self) -> TenantDependancySelector[T]:
        return TenantDependancySelector[self.settings_cls](  # type: ignore[name-defined]
            lambda: load_settings(self.settings_cls),
            (
                TokenHeaderSource,
                PathSource,
                HeaderSource,
                ContextSource,
                TokenBodySource,
                OptionalTokenHeaderSource,
            ),
        )

    def _auth(self) -> VerifiedAuth:
        return VerifiedAuth(self.general)  # type: ignore[arg-type]

    def _optional_auth(self) -> OptionalVerifiedAuth:
        return OptionalVerifiedAuth(self.general)  # type: ignore[arg-type]
