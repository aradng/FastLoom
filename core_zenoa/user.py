from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt
from pydantic import AliasChoices, AnyHttpUrl, BaseModel, Field


def get_current_user(token: str = Depends(OAuth2PasswordBearer(tokenUrl=""))):
    """Return the user based on http connection/request object."""
    return UserPayload.from_jwt(token)


def require_user(
    permissions: set[str] | None = None, is_admin: bool | None = None
):
    forbidden_error = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You don't have access to this endpoint",
    )

    async def user_permission_checker(
        user: UserPayload = Depends(get_current_user),
    ) -> UserPayload:
        if permissions and (not user.tag or user.tag not in permissions):
            raise forbidden_error
        if is_admin is not None and user.is_admin != is_admin:
            raise forbidden_error
        return user

    return user_permission_checker


class UserPayload(BaseModel):
    id: UUID
    email: str
    name: str
    phone: str
    display_name: str = Field(
        ..., validation_alias=AliasChoices("displayName", "display_name")
    )
    avatar: AnyHttpUrl
    tag: str
    is_admin: bool = Field(
        ..., validation_alias=AliasChoices("isAdmin", "is_admin")
    )

    @classmethod
    def from_jwt(cls, token: str) -> "UserPayload":
        jwt_payload = jwt.get_unverified_claims(token)
        return cls(**jwt_payload)
