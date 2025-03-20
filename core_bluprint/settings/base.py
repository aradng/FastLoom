from pathlib import Path

from pydantic import BaseModel, Field, HttpUrl


class IAMSettings(BaseModel):
    IAM_SIDECAR_URL: HttpUrl = Field(
        HttpUrl("http://iam:8000/api/iam/sidecar")
    )
    IAM_TOKEN_URL: Path = Path("/api/iam/auth/login/basic")


class TenantSettings(BaseModel):
    name: str


class TenantWithHostSettings(TenantSettings):
    website_url: HttpUrl | list[HttpUrl]


class MonitoringSettings(BaseModel):
    PROJECT_NAME: str
    ENVIRONMENT: str


class BaseTenantSettings(IAMSettings, TenantSettings, MonitoringSettings): ...


class BaseTenantWithHostSettings(
    IAMSettings, TenantWithHostSettings, MonitoringSettings
): ...
