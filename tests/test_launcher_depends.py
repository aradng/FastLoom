from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from fastloom.launcher.depends import reject_external
from fastloom.settings.base import FastAPISettings
from fastloom.tenant.settings import Configs


def _build_app() -> TestClient:
    configs = Configs.__new__(Configs)
    configs.general = FastAPISettings(PROJECT_NAME="my_service")
    Configs.bind(configs)

    app = FastAPI(root_path="/api/my_service")
    router = APIRouter(dependencies=[Depends(reject_external)])

    @router.get("/ping")
    async def ping() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(router)
    return TestClient(app, base_url="http://testserver")


def test_reject_external_allows_bare_path():
    client = _build_app()
    try:
        assert client.get("/ping").status_code == 200
    finally:
        Configs.bind(None)


def test_reject_external_rejects_prefixed_path():
    client = _build_app()
    try:
        assert client.get("/api/my_service/ping").status_code == 404
    finally:
        Configs.bind(None)
