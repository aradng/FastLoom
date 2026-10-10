from pydantic import BaseModel

from fastloom.settings.utils import EnvBackend, EnvDefault


class LauncherSettings(BaseModel):
    APP_HOST: EnvBackend[str] = EnvDefault("0.0.0.0")
    APP_PORT: int = 8000
    DEBUG: bool = True
    WORKERS: int = 4
    SETTINGS_PUBLIC: bool = False
