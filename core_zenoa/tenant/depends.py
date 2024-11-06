from abc import abstractmethod
from collections.abc import Callable, MutableMapping
from typing import Annotated, Generic

from fastapi import Depends, Header, HTTPException, Path, Request
from faststream.rabbit.fastapi import RabbitMessage
from pydantic import StringConstraints

from core_zenoa.auth.depends import JWTAuth
from core_zenoa.auth.schemas import UserClaims
from core_zenoa.tenant.base.utils import V, get_general_settings
from core_zenoa.tenant.protocols import TenantHostSchema, TenantNameSchema

TenantName = Annotated[str, StringConstraints(strip_whitespace=True)]
TenantMapping = MutableMapping[TenantName, TenantNameSchema]
TenantMappingWithHosts = MutableMapping[TenantName, TenantHostSchema]


class BaseTenantSource[K]:
    settings: MutableMapping[TenantName, K]

    def __init__(self, settings: MutableMapping[TenantName, K]):
        self.settings = settings
        self.general_settings = get_general_settings(settings)

    @abstractmethod
    async def _dep(self, *args, **kwargs) -> str:
        pass

    def get_dep(self) -> Callable[..., str]:
        def _inner(tenant: Annotated[str, Depends(self._dep)]) -> str:
            if tenant not in self.settings:
                raise KeyError(f"Tenant {tenant} not found in settings")
            return tenant

        return _inner


class HeaderSource(BaseTenantSource):
    _hosts: dict[str, str] = dict()

    def __init__(self, settings: TenantMappingWithHosts) -> None:
        super().__init__(settings)
        for tenant in settings.values():
            assert isinstance(tenant.website_url.host, str)
            self._hosts[tenant.website_url.host] = tenant.name

    async def _dep(self, x_forwarded_host: Annotated[str, Header()]) -> str:
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
        if "token" not in (req_json := await req.json()):
            raise HTTPException(
                status_code=400, detail="Token not found in request body."
            )
        return self.auth.parse_token(req_json["token"]).owner


class TokenHeaderSource(BaseTenantSource):
    auth: JWTAuth

    def __init__(self, settings: TenantMapping):
        super().__init__(settings)
        self.auth = JWTAuth(self.general_settings)

    @property
    async def get_claims(self):
        return self.auth.get_claims

    async def _dep(
        self, token: Annotated[UserClaims, Depends(get_claims)]
    ) -> str:
        return token.owner


class ContextSource(BaseTenantSource):
    async def _dep(self, tenant: Annotated[str, RabbitMessage]):
        return tenant


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
    ) -> Callable[..., str]:
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
