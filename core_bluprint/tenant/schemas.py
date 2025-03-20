from pydantic import BaseModel


class TenantMixin(BaseModel):
    tenant: str
