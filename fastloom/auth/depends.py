from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jose.jwt import get_unverified_claims

from fastloom.auth import Claims
from fastloom.auth.protocols import OAuth2Settings
from fastloom.auth.schemas import UserClaims


class OptionalJWTAuth:
    settings: OAuth2Settings
    _oauth2_schema: OAuth2PasswordBearer | None = None

    def __init__(self, settings: OAuth2Settings):
        self.settings = settings
        self._oauth2_schema = OAuth2PasswordBearer(
            str(settings.IAM_TOKEN_URL), auto_error=False
        )

    @classmethod
    def _parse_token(cls, token: str) -> UserClaims:
        return UserClaims.model_validate(get_unverified_claims(token))

    @property
    def get_claims(
        self,
    ) -> Callable[..., Coroutine[Any, Any, UserClaims | None]]:
        async def _inner(
            token: Annotated[str | None, Depends(self._oauth2_schema)],
        ) -> UserClaims | None:
            if token is None:
                return None
            claims = self._parse_token(token)
            Claims.set(claims)
            return claims

        return _inner


class JWTAuth(OptionalJWTAuth):
    def __init__(self, settings: OAuth2Settings):
        super().__init__(settings)
        assert self._oauth2_schema is not None
        self._oauth2_schema.auto_error = True

    @property
    def get_claims(self) -> Callable[..., Coroutine[Any, Any, UserClaims]]:
        async def _inner(
            token: Annotated[str, Depends(self._oauth2_schema)],
        ) -> UserClaims:
            claims = self._parse_token(token)
            Claims.set(claims)
            return claims

        return _inner
