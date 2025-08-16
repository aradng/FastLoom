from pydantic import BaseModel, HttpUrl


class TenantMixin(BaseModel):
    tenant: str


class TenantSettings(BaseModel):
    name: str


class TenantWithHostSettings(TenantSettings):
    website_url: HttpUrl | list[HttpUrl]
