from collections.abc import MutableMapping
from contextlib import suppress
from types import new_class
from typing import TYPE_CHECKING, Annotated, TypeVar

from pydantic import BaseModel, StringConstraints

from fastloom.auth.depends import (
    JWTAuth,
    OptionalJWTAuth,
)
from fastloom.cache.base import BaseCache, BaseTenantSettingCache
from fastloom.cache.lifehooks import RedisHandler
from fastloom.db.signals import BaseDocumentSignal

if TYPE_CHECKING:
    from aredis_om.model.model import NotFoundError

    from fastloom.db.schemas import BaseTenantSettingsDocument
else:
    try:
        from fastloom.db.schemas import BaseTenantSettingsDocument
    except ImportError:
        BaseTenantSettingsDocument = BaseModel

    try:
        from aredis_om.model.model import NotFoundError
    except ImportError:
        NotFoundError = Exception

from fastloom.cache.settings import RedisSettings
from fastloom.db.settings import MongoSettings
from fastloom.meta import SelfSustaining
from fastloom.settings.base import MonitoringSettings
from fastloom.tenant.depends import (
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
from fastloom.tenant.protocols import TenantHostSchema, TenantNameSchema
from fastloom.tenant.utils import (
    DEFAULT_CONFIG_KEY,
    SettingCacheSchema,
    load_settings,
)

TenantName = Annotated[str, StringConstraints(strip_whitespace=True)]
TenantMapping = MutableMapping[TenantName, TenantNameSchema]
TenantMappingWithHosts = MutableMapping[TenantName, TenantHostSchema]


class GetSettingsFrom[V](BaseGetFrom):
    async def _item_getter(self, tenant: str) -> V:
        return await Configs[BaseModel, V].self.get(tenant)  # type: ignore[type-var, misc]


class Configs[T: BaseModel, V: BaseModel](SelfSustaining):
    settings: MutableMapping[str, T]
    general: T
    from_: TenantDependancySelector[T]
    settings_from: GetSettingsFrom[V]
    auth: JWTAuth
    optional_auth: OptionalJWTAuth
    documents_enabled: bool = False
    cache_enabled: bool = False
    service_cls: type[T]
    tenant_cls: type[V]
    # cache
    tenant_schema: SettingCacheSchema[V]

    def __init__(
        self,
        service_cls: type[T],
        tenant_cls: type[V],
    ) -> None:
        if self.self is not None:
            return
        super().__init__()
        self.tenant_cls = tenant_cls
        self.service_cls = service_cls
        self.tenant_schema = SettingCacheSchema(self.tenant_cls)
        self._load_settings_yaml()
        self._load_tenant_yaml()
        self.from_ = self._from_()
        self.settings_from = GetSettingsFrom[V](self.from_)
        self.auth = self._auth()
        self.optional_auth = self._optional_auth()
        self._setup_mongo()
        self._setup_redis()

    def _setup_mongo(self):
        if not issubclass(self.service_cls, MongoSettings):
            return

        self.documents_enabled = True

        if isinstance(self.general, MonitoringSettings):
            BaseDocumentSignal._PROJECT_NAME = self.general.PROJECT_NAME

    def _setup_redis(self):
        if not issubclass(self.service_cls, RedisSettings):
            return

        self.cache_enabled = RedisHandler.enabled

        redis = RedisHandler(self.general).redis
        BaseCache.Meta.database = redis
        BaseTenantSettingCache.Meta.database = redis
        self.tenant_schema.cache.Meta.database = redis

        if isinstance(self.general, MonitoringSettings):
            narrowed_general = self.general
            self.tenant_schema.cache.Meta.model_key_prefix = (
                f"{narrowed_general.PROJECT_NAME}"
            )

    def _load_settings_yaml(self):
        self.settings = load_settings(
            new_class(
                "_SettingsWithTenants",
                (self.service_cls, self.tenant_cls),
            ),
        )
        # ^backward compatibility
        self.general = self.service_cls.model_validate(
            load_settings(self.service_cls, defaults_only=True)[
                DEFAULT_CONFIG_KEY
            ],
            from_attributes=True,
            extra="ignore",
        )

    def _load_tenant_yaml(
        self,
    ):
        self.tenant_schema.config_default = load_settings(
            settings_cls=self.tenant_schema.config,
            defaults_only=True,
        )[DEFAULT_CONFIG_KEY].model_dump()

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

    def _auth(self) -> JWTAuth:
        return JWTAuth(self.general)  # type: ignore[arg-type]

    def _optional_auth(self) -> OptionalJWTAuth:
        return OptionalJWTAuth(self.general)  # type: ignore[arg-type]

    def __getitem__(self, tenant: str):  # farming keks
        return self.get(tenant)

    async def get(self, tenant: str) -> V:
        if self.cache_enabled:
            with suppress(NotFoundError):
                return self.tenant_schema.validate(
                    await self.tenant_schema.cache.get(tenant),
                )
        if self.documents_enabled:
            result = await self.tenant_schema.document.get(tenant)
            if result is not None:
                if self.cache_enabled:
                    await self.tenant_schema.cache.model_validate(
                        result.model_dump()
                    ).save()
                    # ^save in cache for better access time
                return self.tenant_schema.validate(result)
        if tenant in self.settings:
            return self.tenant_schema.model.model_validate(
                self.settings[tenant].model_dump()
            )
        raise TenantNotFound(tenant)

    def __setitem__(self, tenant: str, value: V):  # farming lels
        return self.set(tenant, value)

    async def set(self, tenant: str, value: V):
        # strip defaults before saving
        stripped = self.tenant_schema.strip_defaults(value) | {"id": tenant}
        if self.cache_enabled:
            await self.tenant_schema.cache.model_validate(stripped).save()
        if self.documents_enabled:
            await self.tenant_schema.document.model_validate(stripped).save()


T = TypeVar("T", bound=BaseModel)
ConfigAlias = Configs[T, BaseModel]
