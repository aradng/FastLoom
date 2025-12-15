from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    computed_field,
)

from fastloom.auth.schemas import OAuth2MergedScheme, OIDCCScheme
from fastloom.settings.utils import get_env_or_err
from fastloom.types import Str


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


class IAMSettings(OAuth2MergedScheme, OIDCCScheme):
    INTROSPECT: bool = False
    ACL: bool = False
    IAM_SIDECAR_URL: Str[HttpUrl] | None = Field(None, validate_default=True)


class MonitoringSettings(ProjectSettings):
    ENVIRONMENT: str


class BaseGeneralSettings(IAMSettings, MonitoringSettings): ...
