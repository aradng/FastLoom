from fastapi.openapi.models import OAuthFlow, OAuthFlows
from pydantic import BaseModel, Field, HttpUrl, computed_field, field_validator

from fastloom.types import Str

ADMIN_ROLE = "ADMIN"


class OAuth2MergedScheme(OAuthFlow):
    authorizationUrl: Str[HttpUrl] | None = None
    tokenUrl: Str[HttpUrl] | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def flows(self) -> OAuthFlows:
        if self.authorizationUrl is None and self.tokenUrl is None:
            return OAuthFlows()
        return OAuthFlows.model_validate(
            dict(
                authorizationCode=self.model_dump(
                    exclude_computed_fields=True
                ),
            )
        )
        # ^ implicit & ROPC are deprecated in OAUTH2.1

    @computed_field  # type: ignore[prop-decorator]
    @property
    def oauth2_enabled(self) -> bool:
        return self.authorizationUrl is not None and self.tokenUrl is not None


class OIDCCScheme(BaseModel):
    OIDC_URL: Str[HttpUrl] | None = None

    @computed_field  # type: ignore[misc]
    @property
    def oidc_enabled(self) -> bool:
        return self.OIDC_URL is not None


class IntrospectionResponse(BaseModel):
    active: bool


class Role(BaseModel):
    name: str
    users: list[str] | None = None


class UserClaims(BaseModel):
    tenant: str = Field(alias="owner")
    id: str
    username: str = Field(..., validation_alias="name")
    email: str | None = None
    phone: str | None = None
    roles: list[Role] = Field(default_factory=list)

    @field_validator("roles", mode="before")
    @classmethod
    def validate_roles(cls, v: list[Role] | None) -> list[Role]:
        if not v:
            return []
        return v

    @computed_field  # type: ignore[misc]
    @property
    def is_admin(self) -> bool:
        return any(role.name == ADMIN_ROLE for role in self.roles or [])
