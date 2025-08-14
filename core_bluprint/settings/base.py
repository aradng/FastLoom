from pathlib import Path

from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    PrivateAttr,
    computed_field,
    model_validator,
)


class GeneralSettings(BaseModel):
    PROJECT_NAME: str = Field(default_factory=lambda: Path.cwd().name)
    _is_derived: bool = PrivateAttr(default=False)

    @model_validator(mode="before")
    @classmethod
    def check_derived(cls, data: dict) -> dict:
        if "PROJECT_NAME" not in data:
            cls._is_derived = True
        return data


class FastAPISettings(GeneralSettings):
    DEBUG: bool = True

    @computed_field  # type: ignore[misc]
    @property
    def API_PREFIX(self) -> str:
        return f"/api/{self.PROJECT_NAME}"


class IAMSettings(BaseModel):
    IAM_SIDECAR_URL: HttpUrl = Field(
        HttpUrl("http://iam:8000/api/iam/sidecar")
    )
    IAM_TOKEN_URL: HttpUrl | Path = Path("/api/iam/auth/login/basic")


class TenantSettings(BaseModel):
    name: str


class TenantWithHostSettings(TenantSettings):
    website_url: HttpUrl | list[HttpUrl]


class MonitoringSettings(GeneralSettings):
    ENVIRONMENT: str


class BaseTenantSettings(IAMSettings, TenantSettings, MonitoringSettings): ...


class BaseTenantWithHostSettings(
    IAMSettings, TenantWithHostSettings, MonitoringSettings, FastAPISettings
): ...
