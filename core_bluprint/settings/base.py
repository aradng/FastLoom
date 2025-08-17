from os import getenv
from pathlib import Path

from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    PrivateAttr,
    computed_field,
    model_validator,
)


class ProjectSettings(BaseModel):
    PROJECT_NAME: str = Field(default_factory=lambda: Path.cwd().name)
    _is_derived: bool = PrivateAttr(default=False)

    @model_validator(mode="before")
    @classmethod
    def check_derived(cls, data: dict) -> dict:
        if (PROJECT_NAME := getenv("PROJECT_NAME")) is not None:
            data["PROJECT_NAME"] = PROJECT_NAME
        if "PROJECT_NAME" not in data:
            cls._is_derived = True
        return data


class FastAPISettings(ProjectSettings):
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


class MonitoringSettings(ProjectSettings):
    ENVIRONMENT: str


class BaseGeneralSettings(IAMSettings, MonitoringSettings): ...
