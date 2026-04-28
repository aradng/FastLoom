from re import Pattern

from pydantic import (
    BaseModel,
    Field,
    computed_field,
)

from fastloom.meta import infer_project_name


class ProjectSettings(BaseModel):
    PROJECT_NAME: str = Field(default_factory=infer_project_name)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def API_PREFIX(self) -> str:
        return f"/api/{self.PROJECT_NAME}"


class FastAPISettings(ProjectSettings):
    DEBUG: bool = True
    EXCLUDED_ENDPOINTS: tuple[Pattern | str, ...] = (
        r"/api/\w+/healthcheck",
        r"/healthcheck",
    )


class MonitoringSettings(ProjectSettings):
    ENVIRONMENT: str
