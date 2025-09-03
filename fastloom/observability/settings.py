from pydantic import AnyHttpUrl

from fastloom.settings.base import MonitoringSettings


class ObservabilitySettings(MonitoringSettings):
    SENTRY_ENABLED: int = 0
    OTEL_ENABLED: int = 0
    SENTRY_DSN: AnyHttpUrl | None = None
    METRICS: bool = False
