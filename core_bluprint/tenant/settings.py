from collections.abc import MutableMapping
from pathlib import Path
from types import new_class
from typing import Annotated, Any, Generic, TypeVar, cast

import yaml
from aredis_om.model.model import NotFoundError  # type: ignore[import-untyped]
from pydantic import BaseModel, RootModel, StringConstraints

from core_bluprint.auth.introspect.depends import (
    OptionalVerifiedAuth,
    VerifiedAuth,
)
from core_bluprint.cache.base import BaseTenantSettingCache
from core_bluprint.cache.lifehooks import RedisHandler
from core_bluprint.db.schemas import BaseTenantSettingsDocument
from core_bluprint.db.settings import MongoSettings
from core_bluprint.meta import SelfSustaining
from core_bluprint.settings.base import MonitoringSettings
from core_bluprint.tenant.depends import (
    BaseGetFrom,
    ContextSource,
    HeaderSource,
    OptionalTokenHeaderSource,
    PathSource,
    TenantDependancySelector,
    TenantNotFound,
    TokenBodySource,
    TokenHeaderSource,
)
from core_bluprint.tenant.protocols import TenantHostSchema, TenantNameSchema

DEFAULT_CONFIG_KEY: str = "default"


T = TypeVar("T", bound=BaseModel)
V = TypeVar("V", bound=BaseModel)

TenantName = Annotated[str, StringConstraints(strip_whitespace=True)]
TenantMapping = MutableMapping[TenantName, TenantNameSchema]
TenantMappingWithHosts = MutableMapping[TenantName, TenantHostSchema]


def load_settings(
    settings_cls: type[T],
    config_yml_file: Path | None = None,
    defaults_only=False,
) -> MutableMapping[str, T]:
    config_yml_file = config_yml_file or Path.cwd() / "tenants.yaml"
    _loaded_configs: dict[str, Any]
    with config_yml_file.open() as f:
        _loaded_configs = yaml.safe_load(f)

    _default_config: dict[str, Any] = _loaded_configs.pop(
        DEFAULT_CONFIG_KEY, {}
    )
    if defaults_only:
        return {
            DEFAULT_CONFIG_KEY: settings_cls.model_validate(_default_config)
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


class GetSettingsFrom[V](BaseGetFrom):
    async def _item_getter(self, tenant: str) -> V:
        return await Configs[BaseModel, V].self.get(tenant)  # type: ignore[type-var, misc]


class Configs(Generic[T, V], SelfSustaining):
    settings: MutableMapping[str, T]
    service_settings_cls: type[T]
    general: T
    from_: TenantDependancySelector[T]
    settings_from: GetSettingsFrom[V]
    auth: VerifiedAuth
    optional_auth: OptionalVerifiedAuth
    # cache
    tenant_cache_cls: type[BaseTenantSettingCache] | None
    tenant_document_cls: type[BaseTenantSettingsDocument] | None

    def __init__(
        self,
        settings_cls: type[T],
        tenant_cls: type[V],
        config_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.settings = load_settings(
            new_class(
                "_SettingsWithTenants",
                (settings_cls, tenant_cls),
            ),
            config_path,
        )
        self.general = load_settings(
            settings_cls, config_path, defaults_only=True
        )[DEFAULT_CONFIG_KEY]
        self.service_settings_cls = settings_cls
        self.tenant_settings_cls = tenant_cls
        self.from_ = self._from_()
        self.settings_from = GetSettingsFrom[V](self.from_)
        self.auth = self._auth()
        self.optional_auth = self._optional_auth()
        if issubclass(settings_cls, MongoSettings):
            self.tenant_document_cls = new_class(
                "_TenantSettingsDocument",
                (BaseTenantSettingsDocument, tenant_cls),
            )
        if isinstance(self.general, MonitoringSettings):
            narrowed_general = self.general
            self.tenant_cache_cls = new_class(
                "_TenantSettingsCache",
                (BaseTenantSettingCache, tenant_cls),
                {"index": True},
            )
            self.tenant_cache_cls.Meta.model_key_prefix = (
                f"{narrowed_general.ENVIRONMENT}:"
                f"{narrowed_general.PROJECT_NAME}"
            )

    def _from_(self) -> TenantDependancySelector[T]:
        return TenantDependancySelector[self.service_settings_cls](  # type: ignore[name-defined]
            settings=self.settings,
            general=self.general,
            source_clses=(
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

    def __getitem__(self, tenant: str):  # farming keks
        return self.get(tenant)

    async def get(self, tenant: str) -> V:
        if self.tenant_cache_cls is not None and RedisHandler.enabled:
            try:
                return cast(V, await self.tenant_cache_cls.get(tenant))
            except NotFoundError:
                ...
        if self.tenant_document_cls is not None:
            result = await self.tenant_document_cls.find_one(
                self.tenant_document_cls.tenant == tenant
            )
        if result is not None:
            if self.tenant_cache_cls is not None and RedisHandler.enabled:
                await self.tenant_cache_cls.model_validate(
                    result, from_attributes=True
                ).save()
                # ^save in cache for better access time
            return cast(V, result)
        if result is None and tenant in self.settings:
            return cast(V, self.settings[tenant])
        raise TenantNotFound(tenant)


ConfigAlias = Configs[T, BaseModel]
