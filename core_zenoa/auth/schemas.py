from pydantic import BaseModel, Field, computed_field


class Role(BaseModel):
    name: str
    users: list[str] | None = None


class UserClaims(BaseModel):
    owner: str = Field(title="Owner")
    id: str | None = Field(None, title="Id")
    username: str = Field(..., title="Name", validation_alias="name")
    email: str | None = Field(None, title="Email")
    phone: str | None = Field(None, title="Phone")
    roles: list[Role] | None = Field(default_factory=list, title="Roles")
    country_code: str = Field(
        ..., title="CountryCode", validation_alias="countryCode"
    )

    @computed_field  # type: ignore[misc]
    @property
    def prefix_code(self) -> str | None:
        return {
            "IR": "+98",
            "US": "+1",
        }.get(self.country_code)

    @computed_field  # type: ignore[misc]
    @property
    def tenant(self) -> str:
        return self.owner
