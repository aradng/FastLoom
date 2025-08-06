from pydantic import BaseModel, Field, computed_field, field_validator

ADMIN_ROLE = "ADMIN"


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
