from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from jose.jwt import get_unverified_claims

from core_zenoa.auth.protocols import OAuth2Settings
from core_zenoa.auth.schemas import UserClaims


class JWTAuth:
    oauth2_schema: OAuth2PasswordBearer | None = None
    settings: OAuth2Settings

    def __init__(self, settings: OAuth2Settings):
        self.settings = settings
        self.oauth2_schema = OAuth2PasswordBearer(str(settings.IAM_TOKEN_URL))

    @classmethod
    def parse_token(cls, token: str):
        return UserClaims.model_validate(get_unverified_claims(token))

    async def get_claims(
        self, request: Request, token: Annotated[str, Depends(oauth2_schema)]
    ) -> UserClaims:
        return self.parse_token(token)
