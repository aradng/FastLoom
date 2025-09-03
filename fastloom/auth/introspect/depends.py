from collections.abc import Callable, Coroutine
from typing import Annotated, Any

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer

from fastloom.auth.depends import JWTAuth, OptionalJWTAuth
from fastloom.auth.introspect.schema import IntrospectionResponse
from fastloom.auth.protocols import SidecarSettings
from fastloom.auth.schemas import UserClaims


class OptionalVerifiedAuth(OptionalJWTAuth):
    settings: SidecarSettings
    _oauth2_schema: OAuth2PasswordBearer | None = None

    def __init__(self, settings: SidecarSettings):
        super().__init__(settings)

    async def _introspect(
        self, token: Annotated[str, Depends(_oauth2_schema)]
    ):
        async with httpx.AsyncClient() as client:
            response: httpx.Response = await client.post(
                f"{self.settings.IAM_SIDECAR_URL}/introspect",
                json=dict(token=token),
            )
        if response.status_code != 200:
            raise HTTPException(status_code=403, detail=response.text)
        data = IntrospectionResponse.model_validate(response.json())
        if not data.active:
            raise HTTPException(status_code=403, detail="Inactive token")

    async def _acl(
        self, request: Request, token: Annotated[str, Depends(_oauth2_schema)]
    ) -> None:
        async with httpx.AsyncClient() as client:
            response: httpx.Response = await client.post(
                url=f"{self.settings.IAM_SIDECAR_URL}/acl",
                json={
                    "token": token,
                    "endpoint": request.url.path,
                    "method": request.method,
                },
            )

        if response.status_code != 200:
            raise HTTPException(status_code=403, detail=response.text)
        if not response.json():
            raise HTTPException(status_code=403)

    @property
    def get_claims(
        self,
    ) -> Callable[..., Coroutine[Any, Any, UserClaims | None]]:
        async def _inner(
            request: Request, token: str | None = Depends(self._oauth2_schema)
        ) -> UserClaims | None:
            if token is None:
                return None
            await self._introspect(token)
            await self._acl(request, token)
            return await super(OptionalVerifiedAuth, self).get_claims(token)

        return _inner


class VerifiedAuth(JWTAuth, OptionalVerifiedAuth):
    @property
    def get_claims(self) -> Callable[..., Coroutine[Any, Any, UserClaims]]:
        async def _inner(
            request: Request, token: str = Depends(self._oauth2_schema)
        ) -> UserClaims:
            await self._introspect(token)
            await self._acl(request, token)
            return await super(VerifiedAuth, self).get_claims(token)

        return _inner
