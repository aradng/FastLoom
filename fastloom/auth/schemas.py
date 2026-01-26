from typing import Annotated
from uuid import UUID

from fastapi.openapi.models import OAuthFlow, OAuthFlows
from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    HttpUrl,
    computed_field,
)

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


class OrganizationAttributes(BaseModel):
    id: UUID


class Organization(OrganizationAttributes):
    name: str


class UserClaims(BaseModel):
    iss: HttpUrl
    id: str = Field(alias="sub")
    session_id: str = Field(alias="sid")
    username: str = Field(alias="preferred_username")
    name: str
    given_name: str
    family_name: str
    roles: list[str] = Field(default_factory=list)
    email: str
    email_verified: bool
    scope: Annotated[
        set[str],
        BeforeValidator(lambda v: v.split(" ") if isinstance(v, str) else v),
    ]
    groups: set[str]
    organizations: dict[str, OrganizationAttributes] = Field(
        default_factory=dict
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tenant(self) -> str:
        assert self.iss.path is not None
        return self.iss.path.split("/")[-1]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def organization(self) -> Organization | None:
        if self.organizations:
            org_name = next(iter(self.organizations.keys()))
            return Organization.model_validate(
                {
                    "name": org_name,
                    **self.organizations[org_name].model_dump(),
                }
            )
        return None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_admin(self) -> bool:
        return ADMIN_ROLE in self.roles
