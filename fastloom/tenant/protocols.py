from typing import Protocol

from pydantic import AnyHttpUrl


class TenantNameSchema(Protocol):
    name: str


class TenantHostSchema(TenantNameSchema, Protocol):
    website_url: AnyHttpUrl | list[AnyHttpUrl]


class TenantMonitoringSchema(Protocol):
    PROJECT_NAME: str
    ENVIRONMENT: str
