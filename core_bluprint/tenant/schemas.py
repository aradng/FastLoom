from pydantic import AnyHttpUrl, BaseModel

WebsiteUrlType = AnyHttpUrl


class TenantMixin(BaseModel):
    tenant: str


class BaseTenantWithHostSettings(BaseModel):
    website_url: WebsiteUrlType | list[WebsiteUrlType]
