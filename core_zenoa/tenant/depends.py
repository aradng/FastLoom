from abc import abstractmethod
from collections.abc import Callable, MutableMapping
from json import JSONDecodeError
from typing import Annotated, Generic

from fastapi import Depends, Header, HTTPException, Path, Request
from pydantic import StringConstraints
from pydantic_core import Url

from core_zenoa.auth.depends import JWTAuth, OptionalJWTAuth
from core_zenoa.auth.schemas import UserClaims
from core_zenoa.tenant.base.utils import V, get_general_settings
from core_zenoa.tenant.protocols import TenantHostSchema, TenantNameSchema

TenantName = Annotated[str, StringConstraints(strip_whitespace=True)]
TenantMapping = MutableMapping[TenantName, TenantNameSchema]
TenantMappingWithHosts = MutableMapping[TenantName, TenantHostSchema]


class TenantNotFound(Exception):
    def __init__(self, tenant: str):
        self.tenant = tenant

    def __str__(self):
        return f"Tenant {self.tenant} not found in settings"


class BaseTenantSource[K]:
    settings: MutableMapping[TenantName, K]

    def __init__(self, settings: MutableMapping[TenantName, K]):
        self.settings = settings
        self.general_settings = get_general_settings(settings)

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


class HeaderSource(BaseTenantSource):
    _hosts: dict[str, str] = dict()

    def __init__(self, settings: TenantMappingWithHosts) -> None:
        super().__init__(settings)
        for tenant in settings.values():
            if isinstance(tenant.website_url, Url):
                tenant.website_url = [tenant.website_url]
            assert isinstance(tenant.website_url, list)
            self._hosts.update(
                {
                    url.host: tenant.name
                    for url in tenant.website_url
                    if isinstance(url.host, str)
                }
            )

    async def _dep(
        self, x_forwarded_host: Annotated[str, Header(include_in_schema=False)]
    ) -> str:
        return self._hosts[x_forwarded_host]


class PathSource(BaseTenantSource):
    async def _dep(self, tenant: Annotated[str, Path()]) -> str:
        return tenant


class TokenBodySource(BaseTenantSource):
    auth: JWTAuth

    def __init__(self, settings: TenantMapping) -> None:
        super().__init__(settings)
        self.auth = JWTAuth(self.general_settings)

    async def _dep(self, req: Request) -> str:
        try:
            if "token" not in (req_json := await req.json()):
                raise HTTPException(
                    status_code=400, detail="Token not found in request body."
                )
        except JSONDecodeError:
            raise HTTPException(
                status_code=400, detail="Request body is not JSON decodable."
            )
        return self.auth._parse_token(req_json["token"]).tenant


class OptionalTokenHeaderSource(BaseTenantSource):
    auth: OptionalJWTAuth
    _auth_cls = OptionalJWTAuth

    def __init__(self, settings: TenantMapping):
        super().__init__(settings)
        self.auth = self._auth_cls(self.general_settings)

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


class TokenHeaderSource(OptionalTokenHeaderSource):
    auth: JWTAuth
    _auth_cls = JWTAuth

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


class TenantDependancySelector(Generic[V]):
    def __init__(
        self,
        settings: MutableMapping[str, V],
        source_clses: tuple[type[BaseTenantSource], ...],
    ) -> None:
        self._settings = settings
        self._sources = {
            source_cls.__name__: source_cls(settings)
            for source_cls in source_clses
        }

    def __getitem__(
        self, source_cls: type[BaseTenantSource]
    ) -> Callable[..., str | None]:
        return self._sources[source_cls.__name__].get_dep()


class BaseGetFrom[V]:
    settings: MutableMapping[str, V]
    dep_selector: TenantDependancySelector

    def __init__(
        self,
        settings: MutableMapping[str, V],
        dep_selector: TenantDependancySelector,
    ) -> None:
        self.settings = settings
        self.dep_selector = dep_selector

    @abstractmethod
    def _item_getter(self, tenant: str): ...

    def __getitem__(
        self, source_cls: type[BaseTenantSource]
    ) -> Callable[..., V]:
        def _inner(
            tenant: Annotated[str, Depends(self.dep_selector[source_cls])],
        ) -> V:
            return self._item_getter(tenant)

        return _inner


class GetSettingsFrom[V](BaseGetFrom):
    def _item_getter(self, tenant: str) -> V:
        return self.settings[tenant]
