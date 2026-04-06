from fastloom.auth.settings import IAMSettings
from fastloom.logging.settings import LoggingSettings
from fastloom.settings.base import FastAPISettings, MonitoringSettings


class BaseGeneralSettings(
    IAMSettings, LoggingSettings, MonitoringSettings, FastAPISettings
): ...
