from typing import Literal

from pydantic import BaseModel


class LoggingSettings(BaseModel):
    LOG_LEVEL: (
        int | Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    ) = "INFO"
