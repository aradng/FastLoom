from pathlib import Path
from textwrap import dedent

import pytest

from fastloom.policy import main as cli
from fastloom.policy.rego import COVERAGE, pattern, read_routes, render
from fastloom.policy.source import PolicySourceError
from fastloom.policy.source import read_routes as read_service_routes

FILES = {
    "pyproject.toml": """
        [project]
        name = "shop"
    """,
    "app.py": """
        from fastloom.launcher.schemas import App

        from shop.api import admin, chart, hooks, internal, items

        routes = [
            (items.router, "/items", "Items"),
            (admin.router, "/admin", "Admin"),
            (chart.router, "/chart", "Chart"),
            (internal.router, "/internal/shop", "Internal"),
            (hooks.router, "", "Hooks"),
        ]

        app = App(routes=routes)
    """,
    "shop/__init__.py": "",
    "shop/constants.py": """
        STATS = "/stats"
    """,
    "shop/api/__init__.py": "",
    "shop/api/items.py": """
        from fastapi import APIRouter

        router = APIRouter()


        @router.get("")
        async def list_items(): ...


        @router.delete("/{item_id}")
        async def delete_item(item_id: str): ...


        @router.api_route(
            "/{item_id}/notes/{rest:path}", methods=["GET", "PUT"]
        )
        async def notes(): ...
    """,
    "shop/api/admin.py": """
        from fastapi import APIRouter

        from shop.constants import STATS

        router = APIRouter(prefix="/v1")


        @router.get(STATS)
        async def stats(): ...
    """,
    "shop/api/chart/__init__.py": """
        from fastapi import APIRouter

        from shop.api.chart import dashboard

        router = APIRouter()
        router.include_router(dashboard.router, prefix="/dashboard")


        @router.get("")
        async def charts(): ...
    """,
    "shop/api/chart/dashboard.py": """
        from fastapi import APIRouter

        router = APIRouter(prefix="/boards")


        @router.get("/{board_id}")
        async def board(board_id: str): ...
    """,
    "shop/api/internal.py": """
        from fastapi import APIRouter, Depends
        from fastloom.launcher.depends import reject_external

        router = APIRouter(dependencies=[Depends(reject_external)])


        @router.post("/map")
        async def map_trades(): ...
    """,
    "shop/api/hooks.py": """
        from fastapi import APIRouter

        router = APIRouter()


        @router.post("/webhook")
        async def webhook(): ...
    """,
}


@pytest.fixture
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name, content in FILES.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dedent(content))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["fastloom-policy"])
    return tmp_path


def _routes(service: Path) -> set[tuple[str, str]]:
    return {(r.method, r.path) for r in read_service_routes(service)}


def test_every_route_is_read_with_its_full_path(service: Path):
    assert _routes(service) == {
        ("GET", "/api/shop/items"),
        ("DELETE", "/api/shop/items/{item_id}"),
        ("GET", "/api/shop/items/{item_id}/notes/{rest:path}"),
        ("PUT", "/api/shop/items/{item_id}/notes/{rest:path}"),
        ("GET", "/api/shop/admin/v1/stats"),
        ("GET", "/api/shop/chart"),
        ("GET", "/api/shop/chart/dashboard/boards/{board_id}"),
        ("POST", "/internal/shop/map"),
        ("POST", "/api/shop/webhook"),
    }


def _replace(service: Path, name: str, old: str, new: str) -> None:
    path = service / name
    assert old in path.read_text()
    path.write_text(path.read_text().replace(old, new))


@pytest.mark.parametrize(
    ("name", "old", "new", "message"),
    [
        (
            "shop/api/admin.py",
            "@router.get(STATS)",
            '@router.get(f"/{STATS}")',
            "f-string",
        ),
        (
            "shop/api/hooks.py",
            "router = APIRouter()\n",
            'router = APIRouter()\nrouter.add_api_route("/x", webhook)\n',
            "add_api_route",
        ),
        (
            "shop/api/internal.py",
            "dependencies=[Depends(reject_external)]",
            "dependencies=GUARDS",
            "literal list",
        ),
        (
            "shop/api/chart/__init__.py",
            "router.include_router(dashboard.router",
            "router.include_router(make_router()",
            "not an APIRouter",
        ),
    ],
)
def test_what_cannot_be_read_without_running_the_code_fails(
    service: Path, name: str, old: str, new: str, message: str
):
    _replace(service, name, old, new)

    with pytest.raises(PolicySourceError, match=message):
        read_service_routes(service)


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("/api/shop/openapi.json", r"^/api/shop/openapi\.json$"),
        ("/api/shop/items/{item_id}", "^/api/shop/items/[^/]+$"),
        ("/api/iam/check/{rest:path}", "^/api/iam/check/.+$"),
    ],
)
def test_a_route_template_becomes_an_escaped_pattern(template, expected):
    assert pattern(template) == expected


def test_the_rendered_route_list_reads_back(service: Path):
    assert read_routes(render(read_service_routes(service))) == _routes(
        service
    )


def test_the_command_writes_the_routes_and_tests_then_reports_changes(
    service: Path, capsys: pytest.CaptureFixture[str]
):
    assert cli.main() == 1
    assert (service / "policy/routes_test.rego").read_text() == COVERAGE
    assert cli.main() == 0
    capsys.readouterr()

    _replace(
        service,
        "shop/api/hooks.py",
        '@router.post("/webhook")',
        '@router.put("/webhook")',
    )

    assert cli.main() == 1
    out = capsys.readouterr().out
    assert "+ PUT /api/shop/webhook" in out
    assert "- POST /api/shop/webhook" in out
