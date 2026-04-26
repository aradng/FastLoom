from typing import Protocol

import logfire
from pydantic import AnyHttpUrl


class TenantNameSchema(Protocol):
    name: str


class TenantHostSchema(TenantNameSchema, Protocol):
    website_url: AnyHttpUrl | list[AnyHttpUrl]


class TenantMonitoringSchema(Protocol):
    PROJECT_NAME: str
    ENVIRONMENT: str
    OTEL_SAMPLING: logfire.SamplingOptions
