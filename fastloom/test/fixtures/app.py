import pytest_asyncio
from fastapi.testclient import TestClient

from fastloom.launcher.main import app
from fastloom.settings.base import FastAPISettings
from fastloom.tenant.settings import ConfigAlias


@pytest_asyncio.fixture
def init_app(
    tenant_name: str,
    TC: ConfigAlias[FastAPISettings],
) -> TestClient:
    return TestClient(
        app=app(),
        base_url=f"http://testserver{TC.general.API_PREFIX}",
        headers={
            "x-forwarded-host": f"{tenant_name}.com",
            "accept-language": "en",
        },
    )
