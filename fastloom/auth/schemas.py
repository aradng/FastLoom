from typing import Annotated, Any
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    HttpUrl,
    computed_field,
    model_serializer,
)

ADMIN_ROLE = "ADMIN"


class Role(BaseModel):
    name: str
    users: list[str] | None = None


class OrganizationAttributes(BaseModel):
    id: UUID


class Organization(OrganizationAttributes):
    name: str


class UserClaims(BaseModel):
    iss: HttpUrl
    id: UUID = Field(alias="sub")
    sid: str = Field(alias="sid")
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
    groups: set[str] = Field(default_factory=set)
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

    @model_serializer(when_used="json")
    def serialize(self) -> dict[str, Any]:
        data = self.model_dump(
            by_alias=True, exclude={"tenant", "organization", "is_admin"}
        )
        data["scope"] = " ".join(self.scope)
        return data
