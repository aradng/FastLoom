from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastloom.launcher.settings import LauncherSettings
from fastloom.settings.base import FastAPISettings
from fastloom.tenant.handler import init_settings_endpoints
from fastloom.tenant.settings import Configs


class _Settings(FastAPISettings, LauncherSettings):
    pass


def _build_app(*, settings_public: bool) -> TestClient:
    configs = Configs.__new__(Configs)
    configs.general = _Settings(
        PROJECT_NAME="my_service", SETTINGS_PUBLIC=settings_public
    )
    configs.tenant_schema = type(
        "_Schema", (), {"get_schema": staticmethod(lambda: {"ok": True})}
    )  # type: ignore[assignment]
    Configs.self = configs  # type: ignore[misc, assignment]

    app = FastAPI(root_path="/api/my_service")
    init_settings_endpoints(app=app, configs=Configs)
    return TestClient(app, base_url="http://testserver")


def test_settings_endpoint_internal_path_always_reachable():
    client = _build_app(settings_public=False)
    try:
        assert client.get("/tenant_schema").status_code == 200
    finally:
        Configs.self = None  # type: ignore[misc, assignment]


def test_settings_endpoint_external_path_rejected_unless_public():
    client = _build_app(settings_public=False)
    try:
        # Envoy forwards the full prefixed path unstripped; root_path
        # would otherwise let this fall through to the same bare route.
        r = client.get("/api/my_service/tenant_schema")
        assert r.status_code == 404
    finally:
        Configs.self = None  # type: ignore[misc, assignment]


def test_settings_endpoint_external_path_allowed_when_public():
    client = _build_app(settings_public=True)
    try:
        assert client.get("/api/my_service/tenant_schema").status_code == 200
        assert client.get("/tenant_schema").status_code == 200
    finally:
        Configs.self = None  # type: ignore[misc, assignment]
