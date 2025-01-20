from pydantic import HttpUrl

from core_zenoa.settings.base import MonitoringSettings


class ObservabilitySettings(MonitoringSettings):
    SENTRY_ENABLED: int = 0
    OTEL_ENABLED: int = 0
    SENTRY_DSN: HttpUrl | None = None
