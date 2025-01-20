from pathlib import Path

from pydantic import BaseModel


class I18nSettings(BaseModel):
    LOCALE_DIR: Path = Path("locale")
