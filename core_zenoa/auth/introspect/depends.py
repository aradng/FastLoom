from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer

from core_zenoa.auth.depends import JWTAuth
from core_zenoa.auth.introspect.schema import IntrospectionResponse
from core_zenoa.auth.protocols import SidecarSettings
from core_zenoa.auth.schemas import UserClaims


class VerifiedAuth(JWTAuth):
    oauth2_schema: OAuth2PasswordBearer | None = None
    settings: SidecarSettings

    def __init__(self, settings: SidecarSettings):
        super().__init__(settings)

    async def introspect(self, token: Annotated[str, Depends(oauth2_schema)]):
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

    async def acl(
        self, request: Request, token: Annotated[str, Depends(oauth2_schema)]
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

    async def get_claims(
        self, request: Request, token: Annotated[str, Depends(oauth2_schema)]
    ) -> UserClaims:
        await self.introspect(token)
        await self.acl(request, token)
        return await super().get_claims(request, token)
