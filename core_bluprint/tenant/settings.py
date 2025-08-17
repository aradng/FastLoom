import logging
from collections.abc import MutableMapping
from contextlib import suppress
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
from core_bluprint.cache.base import (
    BaseServiceSettingCache,
    BaseTenantSettingCache,
)
from core_bluprint.cache.lifehooks import RedisHandler
from core_bluprint.db.schemas import BaseTenantSettingsDocument
from core_bluprint.db.settings import MongoSettings
from core_bluprint.meta import SelfSustaining
from core_bluprint.settings.base import MonitoringSettings, ProjectSettings
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
from core_bluprint.tenant.utils import SettingCacheSchema, run_sync

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
    general: T
    from_: TenantDependancySelector[T]
    settings_from: GetSettingsFrom[V]
    auth: VerifiedAuth
    optional_auth: OptionalVerifiedAuth
    _documents_enabled: bool = False
    # cache
    service_schema: SettingCacheSchema[T, BaseModel, BaseServiceSettingCache]
    tenant_schema: SettingCacheSchema[
        V, BaseTenantSettingsDocument, BaseTenantSettingCache
    ]

    def __init__(
        self,
        settings_cls: type[T],
        tenant_cls: type[V],
    ) -> None:
        if self.self is not None:
            return
        super().__init__()
        BaseServiceSettingCache.Meta.database = RedisHandler().redis
        BaseTenantSettingCache.Meta.database = RedisHandler().redis
        self.service_schema = SettingCacheSchema(
            settings_cls, BaseModel, BaseServiceSettingCache
        )
        self.tenant_schema = SettingCacheSchema(
            tenant_cls, BaseTenantSettingsDocument, BaseTenantSettingCache
        )
        if not run_sync(self._load_redis()):
            self._load_yaml()
        self.from_ = self._from_()
        self.settings_from = GetSettingsFrom[V](self.from_)
        self.auth = self._auth()
        self.optional_auth = self._optional_auth()
        # cache
        if issubclass(settings_cls, MongoSettings):
            self._documents_enabled = True
        if isinstance(self.general, MonitoringSettings):
            narrowed_general = self.general
            self.tenant_schema.cache.Meta.model_key_prefix = (
                f"{narrowed_general.ENVIRONMENT}:"
                f"{narrowed_general.PROJECT_NAME}"
            )

    def _load_yaml(self):
        # backward compatibility
        self.settings = load_settings(
            new_class(
                "_SettingsWithTenants",
                (self.service_schema.model, self.tenant_schema.model),
            ),
        )
        self.general = load_settings(
            self.service_schema.model, defaults_only=True
        )[DEFAULT_CONFIG_KEY]
        self.tenant_schema.config_default = load_settings(
            settings_cls=self.tenant_schema.config,
            defaults_only=True,
        )[DEFAULT_CONFIG_KEY].model_dump()

    async def _load_redis(self) -> bool:
        PROJECT_NAME = ProjectSettings.model_validate({}).PROJECT_NAME
        if not RedisHandler.enabled:
            return False
        with suppress(NotFoundError):
            self.general = self.service_schema.validate(
                await self.service_schema.cache.get(PROJECT_NAME),
            )
            return True
        logging.warning("Failed to fetch Settings from redis")
        return False

    def _from_(self) -> TenantDependancySelector[T]:
        return TenantDependancySelector[T](
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
        if RedisHandler.enabled:
            try:
                return self.tenant_schema.validate(
                    await self.tenant_schema.cache.get(tenant),
                )
            except NotFoundError:
                ...
        if self._documents_enabled:
            result = await self.tenant_schema.document.find_one(
                self.tenant_schema.document.tenant == tenant
            )
            if result is not None:
                if RedisHandler.enabled:
                    await self.tenant_schema.cache.model_validate(
                        result, from_attributes=True
                    ).save()
                    # ^save in cache for better access time
                return self.tenant_schema.validate(result)
        if result is None and tenant in self.settings:
            return self.tenant_schema.validate(cast(V, self.settings[tenant]))
        raise TenantNotFound(tenant)


ConfigAlias = Configs[T, BaseModel]
