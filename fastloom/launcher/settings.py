from pydantic import BaseModel


class LauncherSettings(BaseModel):
    APP_PORT: int = 8000
    DEBUG: bool = True
    WORKERS: int = 4
    SETTINGS_PUBLIC: bool = False
