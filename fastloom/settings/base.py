from pathlib import Path

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    Field,
    computed_field,
)

from fastloom.settings.utils import get_env_or_err


class ProjectSettings(BaseModel):
    PROJECT_NAME: str = Field(
        default_factory=get_env_or_err("PROJECT_NAME"),
    )


class FastAPISettings(ProjectSettings):
    DEBUG: bool = True

    @computed_field  # type: ignore[misc]
    @property
    def API_PREFIX(self) -> str:
        return f"/api/{self.PROJECT_NAME}"


class IAMSettings(BaseModel):
    IAM_SIDECAR_URL: AnyHttpUrl = Field(
        AnyHttpUrl("http://iam:8000/api/iam/sidecar")
    )
    IAM_TOKEN_URL: AnyHttpUrl | Path = Path("/api/iam/auth/login/basic")


class MonitoringSettings(ProjectSettings):
    ENVIRONMENT: str


class BaseGeneralSettings(IAMSettings, MonitoringSettings): ...
