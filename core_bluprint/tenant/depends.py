from abc import abstractmethod
from collections.abc import Callable, MutableMapping
from itertools import chain
from json import JSONDecodeError
from typing import Annotated, Generic, TypeAliasType, TypeVar

from fastapi import Depends, Header, HTTPException, Path, Request
from pydantic import StringConstraints

from core_bluprint.auth.depends import JWTAuth, OptionalJWTAuth
from core_bluprint.auth.schemas import UserClaims
from core_bluprint.tenant.base.utils import get_general_settings
from core_bluprint.tenant.protocols import TenantHostSchema, TenantNameSchema

TenantName = Annotated[str, StringConstraints(strip_whitespace=True)]
TenantMapping = MutableMapping[TenantName, TenantNameSchema]
TenantMappingWithHosts = MutableMapping[TenantName, TenantHostSchema]
K = TypeVar("K")
SettingsMapping = TypeAliasType(
    "SettingsMapping", MutableMapping[TenantName, K], type_params=(K,)
)
SettingsMappingGetter = TypeAliasType(
    "SettingsMappingGetter", Callable[[], SettingsMapping[K]], type_params=(K,)
)


class TenantNotFound(Exception):
    def __init__(self, tenant: str):
        self.tenant = tenant

    def __str__(self):
        return f"Tenant {self.tenant} not found in settings"


class BaseTenantSource(Generic[K]):
    settings_fn: SettingsMappingGetter[K]

    def __init__(self, settings_fn: SettingsMappingGetter[K]) -> None:
        self.settings_fn = settings_fn

    @abstractmethod
    async def _dep(self, *args, **kwargs) -> str | None:
        pass

    def get_dep(self) -> Callable[..., str | None]:
        def _inner(
            tenant: Annotated[str | None, Depends(self._dep)],
        ) -> str | None:
            if tenant is None:
                return None
            if tenant not in self.settings:
                raise TenantNotFound(tenant)
            return tenant

        return _inner

    @property
    def settings(self) -> SettingsMapping[K]:
        return self.settings_fn()

    @property
    def general_settings(self) -> K:
        return get_general_settings(self.settings)


class HeaderSource(BaseTenantSource[TenantHostSchema]):
    async def _dep(
        self, x_forwarded_host: Annotated[str, Header(include_in_schema=False)]
    ) -> str:
        return self.hosts[x_forwarded_host]

    @property
    def hosts(self) -> dict[str, str]:
        return dict(
            chain(
                *(
                    tuple(
                        (url.host, tenant.name)
                        for url in (
                            tenant.website_url
                            if isinstance(tenant.website_url, list)
                            else [tenant.website_url]
                        )
                        if url.host
                    )
                    for tenant in self.settings.values()
                )
            )
        )


class PathSource(BaseTenantSource):
    async def _dep(self, tenant: Annotated[str, Path()]) -> str:
        return tenant


class TokenBodySource(BaseTenantSource):
    async def _dep(self, req: Request) -> str:
        try:
            if "token" not in (req_json := await req.json()):
                raise HTTPException(
                    status_code=400, detail="Token not found in request body."
                )
        except JSONDecodeError as er:
            raise HTTPException(
                status_code=400, detail="Request body is not JSON decodable."
            ) from er
        return self.auth._parse_token(req_json["token"]).tenant

    @property
    def auth(self) -> JWTAuth:
        return JWTAuth(self.general_settings)


class OptionalTokenHeaderSource(BaseTenantSource):
    def get_dep(self) -> Callable[..., str | None]:
        def _inner(
            claims: Annotated[
                UserClaims | None, Depends(self.auth.get_claims)
            ],
        ) -> str | None:
            if claims is None:
                return None
            return self._get_tenant_from_claims(claims)

        return _inner

    def _get_tenant_from_claims(self, claims: UserClaims) -> str:
        tenant = claims.tenant
        if tenant not in self.settings:
            raise TenantNotFound(tenant)
        return tenant

    @property
    def auth(self) -> OptionalJWTAuth:
        return OptionalJWTAuth(self.general_settings)


class TokenHeaderSource(OptionalTokenHeaderSource):
    def get_dep(self) -> Callable[..., str]:
        def _inner(
            claims: Annotated[UserClaims, Depends(self.auth.get_claims)],
        ) -> str:
            return self._get_tenant_from_claims(claims)

        return _inner


try:
    from faststream import Depends as StreamDepends
    from faststream.rabbit.fastapi import RabbitMessage

    class ContextSource(BaseTenantSource):
        async def _dep(self, tenant: Annotated[str, RabbitMessage]):
            return tenant

    def get_dep(self) -> Callable[..., str | None]:
        def _inner(
            tenant: Annotated[str, StreamDepends(self._dep)],
        ) -> str | None:
            if tenant not in self.settings:
                raise TenantNotFound(tenant)
            return tenant

        return _inner

except ImportError:
    pass


class TenantDependancySelector(Generic[K]):
    settings_fn: SettingsMappingGetter[K]
    source_clses: tuple[type[BaseTenantSource], ...]

    def __init__(
        self,
        settings_fn: SettingsMappingGetter[K],
        source_clses: tuple[type[BaseTenantSource], ...],
    ) -> None:
        self.settings_fn = settings_fn
        self.source_clses = source_clses

    def __getitem__(
        self, source_cls: type[BaseTenantSource]
    ) -> Callable[..., str | None]:
        return self.sources[source_cls.__name__].get_dep()

    @property
    def sources(self) -> dict[TenantName, BaseTenantSource]:
        return {
            source_cls.__name__: source_cls(self.settings_fn)
            for source_cls in self.source_clses
        }


class BaseGetFrom[K]:
    dep_selector: TenantDependancySelector

    def __init__(self, dep_selector: TenantDependancySelector) -> None:
        self.dep_selector = dep_selector

    @abstractmethod
    def _item_getter(self, tenant: str):
        raise NotImplementedError("Must implement _item_getter method")

    def __getitem__(
        self, source_cls: type[BaseTenantSource]
    ) -> Callable[..., K]:
        def _inner(
            tenant: Annotated[str, Depends(self.dep_selector[source_cls])],
        ) -> K:
            return self._item_getter(tenant)

        return _inner


class GetSettingsFrom[K](BaseGetFrom):
    def _item_getter(self, tenant: str) -> K:
        return self.dep_selector.settings_fn()[tenant]
