from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jose.jwt import get_unverified_claims

from core_bluprint.auth.protocols import OAuth2Settings
from core_bluprint.auth.schemas import UserClaims


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
            return self._parse_token(token)

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
            return self._parse_token(token)

        return _inner
