from re import Pattern
from typing import Literal

from fastloom.settings.base import MonitoringSettings


class LoggingSettings(MonitoringSettings):
    LOG_LEVEL: (
        int | Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    ) = "INFO"
    LOGGING_EXCLUDED_ENDPOINTS: tuple[Pattern | str, ...] = (
        r"/api/\w+/healthcheck$",
        r"/healthcheck$",
    )
    LOGGING_EXCLUDED_QUEUES: tuple[Pattern | str, ...] = ()
