import json
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

from fastloom.policy.routes import access_of

SETTINGS = """
from fastloom.launcher.settings import LauncherSettings
from fastloom.observability.settings import ObservabilitySettings
from fastloom.settings.general import BaseGeneralSettings


class Settings(
    BaseGeneralSettings, ObservabilitySettings, LauncherSettings
): ...
"""

APP = """
from typing import Annotated

from fastapi import APIRouter, Depends, Security
from fastapi.security import OpenIdConnect

from fastloom.launcher.schemas import App

oidc = OpenIdConnect(
    openIdConnectUrl="http://iam/.well-known/openid-configuration"
)


def claims(token: Annotated[str, Depends(oidc)]) -> str:
    return token


def admin(token: Annotated[str, Security(claims, scopes=["ADMIN"])]) -> str:
    return token


items = APIRouter()


@items.get("")
def list_items(token: Annotated[str, Depends(claims)]) -> None: ...


@items.delete("/{item_id}")
def delete_item(
    item_id: str, token: Annotated[str, Depends(claims)]
) -> None: ...


admin_router = APIRouter(dependencies=[Depends(admin)])


@admin_router.get("/stats")
def stats() -> None: ...


hooks = APIRouter()


@hooks.post("/webhook")
def webhook() -> None: ...


app = App(
    routes=[
        (items, "/items", "Items"),
        (admin_router, "/admin", "Admin"),
        (hooks, "", "Hooks"),
    ]
)
"""

TENANTS = """
default:
  PROJECT_NAME: shop
  ENVIRONMENT: test
  OIDC_URL: http://iam/.well-known/openid-configuration
"""


@pytest.mark.parametrize(
    ("operation", "access"),
    [
        ({}, "open"),
        ({"security": [{"OpenIdConnect": []}]}, "user"),
        ({"security": [{"OpenIdConnect": ["ADMIN"]}]}, "ADMIN"),
        ({"security": [{"OpenIdConnect": ["B", "A"]}]}, "A+B"),
    ],
)
def test_access_is_read_from_the_security_requirement(operation, access):
    assert access_of(operation) == access


@pytest.fixture
def service(tmp_path: Path) -> Path:
    (tmp_path / "settings.py").write_text(dedent(SETTINGS))
    (tmp_path / "app.py").write_text(dedent(APP))
    (tmp_path / "tenants.yaml").write_text(dedent(TENANTS))
    return tmp_path


def _run(service: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "fastloom.policy.routes",
            "--package",
            "shop",
        ],
        cwd=service,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_manifest_lists_every_route_with_its_access(service: Path):
    result = _run(service)

    assert result.returncode == 1, result.stderr
    routes = {
        (r["method"], r["path"]): r["access"]
        for r in json.loads((service / "policy/routes.json").read_text())[
            "app_routes"
        ]
    }
    assert routes[("GET", "/api/shop/items")] == "user"
    assert routes[("DELETE", "/api/shop/items/{item_id}")] == "user"
    assert routes[("GET", "/api/shop/admin/stats")] == "ADMIN"
    assert routes[("POST", "/api/shop/webhook")] == "open"


def test_the_coverage_tests_are_written_into_the_service_package(
    service: Path,
):
    _run(service)

    coverage = (service / "policy/fastloom_routes_test.rego").read_text()
    assert coverage.startswith("package shop\n")


def test_an_unchanged_service_passes(service: Path):
    _run(service)

    assert _run(service).returncode == 0


def test_a_changed_route_fails_and_names_it(service: Path):
    _run(service)
    app = service / "app.py"
    app.write_text(
        app.read_text().replace(
            '@hooks.post("/webhook")\ndef webhook() -> None: ...',
            '@hooks.post("/webhook")\n'
            "def webhook(token: Annotated[str, Depends(claims)]) -> None: ...",
        )
    )

    result = _run(service)

    assert result.returncode == 1
    assert "POST /api/shop/webhook: open -> user" in result.stdout
