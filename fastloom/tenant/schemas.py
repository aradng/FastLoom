from typing import Annotated

from pydantic import AnyHttpUrl, BaseModel, Field

WebsiteUrlType = AnyHttpUrl


class TenantMixin(BaseModel):
    tenant: str


class BaseTenantWithHostSettings(BaseModel):
    website_url: (
        WebsiteUrlType | Annotated[list[WebsiteUrlType], Field(min_length=1)]
    )
