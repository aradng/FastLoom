from collections.abc import Callable, Coroutine
from typing import Annotated, Any

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2, OpenIdConnect
from jose.jwt import get_unverified_claims

from fastloom.auth import Claims
from fastloom.auth.schemas import (
    IntrospectionResponse,
    UserClaims,
)
from fastloom.settings.base import IAMSettings


class OptionalJWTAuth:
    settings: IAMSettings
    _security_scheme: OAuth2 | OpenIdConnect | None = None

    def __init__(self, settings: IAMSettings):
        self.settings = settings

        if self.settings.oidc_enabled:
            assert self.settings.OIDC_URL is not None
            self._security_scheme = OpenIdConnect(
                openIdConnectUrl=self.settings.OIDC_URL,
                scheme_name="OIDC",
                auto_error=False,
            )
        elif self.settings.oauth2_enabled:
            self._security_scheme = OAuth2(
                flows=self.settings.flows, auto_error=False
            )

    async def _introspect(
        self, token: Annotated[str, Depends(_security_scheme)]
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

    def _transform_bearer(self, token: str) -> str:
        if token.startswith("Bearer "):
            return token.removeprefix("Bearer ").strip()
        return token

    async def _acl(
        self,
        request: Request,
        token: Annotated[str, Depends(_security_scheme)],
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

    @classmethod
    def _parse_token(cls, token: str) -> UserClaims:
        return UserClaims.model_validate(get_unverified_claims(token))

    async def _validate_token(
        self, token: str, request: Request
    ) -> UserClaims:
        token = self._transform_bearer(token)
        if self.settings.INTROSPECT:
            await self._introspect(token)
        if self.settings.ACL:
            await self._acl(request, token)
        claims = self._parse_token(token)
        Claims.set(claims)
        return claims

    @property
    def get_token(
        self,
    ) -> Callable[..., Coroutine[Any, Any, str | None]]:
        async def _inner(
            token: Annotated[str | None, Depends(self._security_scheme)],
        ) -> str | None:
            if token is None:
                return None
            return self._transform_bearer(token)

        return _inner

    @property
    def get_claims(
        self,
    ) -> Callable[..., Coroutine[Any, Any, UserClaims | None]]:
        async def _inner(
            request: Request,
            token: Annotated[str | None, Depends(self._security_scheme)],
        ) -> UserClaims | None:
            if token is None:
                return None

            return await self._validate_token(token, request)

        return _inner


class JWTAuth(OptionalJWTAuth):
    def __init__(self, settings: IAMSettings):
        super().__init__(settings)
        if self._security_scheme is not None:
            self._security_scheme.auto_error = True

    @property
    def get_claims(self) -> Callable[..., Coroutine[Any, Any, UserClaims]]:
        async def _inner(
            request: Request,
            token: Annotated[str, Depends(self._security_scheme)],
        ) -> UserClaims:
            return await self._validate_token(token, request)

        return _inner

    @property
    def get_token(
        self,
    ) -> Callable[..., Coroutine[Any, Any, str]]:
        async def _inner(
            token: Annotated[str, Depends(self._security_scheme)],
        ) -> str:
            return self._transform_bearer(token)

        return _inner
