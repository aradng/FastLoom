from re import Pattern

from pydantic import BaseModel


class LauncherSettings(BaseModel):
    APP_PORT: int = 8000
    DEBUG: bool = True
    WORKERS: int = 4
    SETTINGS_PUBLIC: bool = False
    LOGGING_EXCLUDED_ENDPOINTS: tuple[Pattern | str, ...] = (
        r"/api/\w+/healthcheck$",
        r"/healthcheck$",
    )
