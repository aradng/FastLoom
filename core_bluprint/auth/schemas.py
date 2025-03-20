from pydantic import BaseModel, Field


class Role(BaseModel):
    name: str
    users: list[str] | None = None


class UserClaims(BaseModel):
    tenant: str = Field(alias="owner")
    id: str | None = None
    username: str = Field(..., validation_alias="name")
    email: str | None = None
    phone: str | None = None
    roles: list[Role] | None = Field(default_factory=list)
