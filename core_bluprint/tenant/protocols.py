from typing import Protocol

from pydantic import HttpUrl


class TenantNameSchema(Protocol):
    name: str


class TenantHostSchema(TenantNameSchema, Protocol):
    website_url: HttpUrl | list[HttpUrl]


class TenantMonitoringSchema(Protocol):
    PROJECT_NAME: str
