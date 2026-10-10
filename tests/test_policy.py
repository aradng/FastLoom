import re
import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest
from starlette.routing import compile_path

from fastloom.policy import main as cli
from fastloom.policy.rego import COVERAGE, COVERAGE_FILE, ROUTES_FILE, render
from fastloom.policy.source import PolicySourceError, ServiceSource

FILES = {
    "pyproject.toml": """
        [project]
        name = "shop"
    """,
    "app.py": """
        from fastloom.launcher.schemas import App

        from shop.api import admin, chart, hooks, items

        routes = [
            (items.router, "/items", "Items"),
            (admin.router, "/admin", "Admin"),
            (chart.router, "/chart", "Chart"),
            (hooks.router, "", "Hooks"),
        ]

        app = App(
            routes=routes,
            mounts=[("/files/", object())],
        )
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
    "shop/api/hooks.py": """
        from fastapi import APIRouter

        router = APIRouter()


        @router.post("/webhook")
        async def webhook(): ...


        @router.post("/agent/")
        async def agent(): ...
    """,
}
SHOP_ROUTES = {
    ("GET", "/api/shop/items"),
    ("DELETE", "/api/shop/items/{item_id}"),
    ("GET", "/api/shop/items/{item_id}/notes/{rest:path}"),
    ("PUT", "/api/shop/items/{item_id}/notes/{rest:path}"),
    ("GET", "/api/shop/admin/v1/stats"),
    ("GET", "/api/shop/chart"),
    ("GET", "/api/shop/chart/dashboard/boards/{board_id}"),
    ("POST", "/api/shop/webhook"),
    ("POST", "/api/shop/agent/"),
    ("*", "/api/shop/files/{path:path}"),
}


def write(root: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dedent(content))
    return root


def replace(root: Path, name: str, old: str, new: str) -> None:
    path = root / name
    assert old in path.read_text()
    path.write_text(path.read_text().replace(old, new))


def read(root: Path) -> set[tuple[str, str]]:
    return {(r.method, r.path) for r in ServiceSource(root).routes()}


@pytest.fixture
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return write(tmp_path, FILES)


PHANTOM = {
    "tests/test_hooks.py": (
        "from shop.api.hooks import router\n\n"
        '@router.get("/phantom")\n'
        "async def phantom(): ...\n"
    ),
    "scripts/broken.py": "router.get(\n",
}


@pytest.mark.parametrize(
    ("extra", "relative"),
    [({}, False), ({}, True), (PHANTOM, False)],
    ids=["absolute root", "relative root", "modules nothing imports"],
)
def test_every_route_is_read_with_its_full_path(
    service: Path, extra: dict[str, str], relative: bool
):
    write(service, extra)

    assert read(Path(".") if relative else service) == SHOP_ROUTES


def test_an_app_without_routes_has_none(service: Path):
    write(service, {"app.py": "from x import App\n\napp = App()\n"})

    assert ServiceSource(service).routes() == []


UNREADABLE_CALLS = (
    "add_api_route('/x', webhook)",
    "add_route('/x', webhook)",
    "route('/x')",
    "websocket_route('/x')",
    "mount('/x', object())",
    "host('example.com', object())",
)
FAILURES = {
    "f-string": (
        "shop/api/admin.py",
        "@router.get(STATS)",
        '@router.get(f"/{STATS}")',
        "f-string",
    ),
    **{
        call.partition("(")[0]: (
            "shop/api/hooks.py",
            "router = APIRouter()\n",
            f"router = APIRouter()\nrouter.{call}\n",
            re.escape(call),
        )
        for call in UNREADABLE_CALLS
    },
    "not a router": (
        "shop/api/chart/dashboard.py",
        'router = APIRouter(prefix="/boards")',
        "router = make_router()",
        "not an APIRouter",
    ),
    "named methods": (
        "shop/api/items.py",
        'methods=["GET", "PUT"]',
        "methods=METHODS",
        "literal methods list",
    ),
    "no App": (
        "app.py",
        "app = App(",
        "app = make_app(",
        r"has no App\(...\)",
    ),
    "bare entry": (
        "app.py",
        '(items.router, "/items", "Items"),',
        "items.router,",
        "each route entry must be",
    ),
    "bare mount": (
        "app.py",
        'mounts=[("/files/", object())]',
        'mounts=["/files/"]',
        "each mount must be",
    ),
    "built routes": (
        "app.py",
        "routes=routes,",
        "routes=build(),",
        r"App\(routes=...\) must be a literal list",
    ),
    "rebound": (
        "shop/api/admin.py",
        'router = APIRouter(prefix="/v1")\n',
        'router = APIRouter(prefix="/v1")\nrouter = APIRouter()\n',
        "router is bound more than once",
    ),
    "augmented": (
        "app.py",
        "\napp = App(",
        '\nroutes += [(hooks.router, "/more", "More")]\napp = App(',
        "routes is bound more than once",
    ),
    "appended": (
        "app.py",
        "\napp = App(",
        '\nroutes.append((hooks.router, "/more", "More"))\napp = App(',
        "routes is changed after it is bound",
    ),
    "external constant": (
        "shop/api/admin.py",
        "from shop.constants import STATS",
        "from os.path import sep as STATS",
        "as a string the repo defines",
    ),
    "syntax error": (
        "shop/api/hooks.py",
        "async def agent(): ...",
        "async def agent(: ...",
        "shop.api.hooks: cannot parse",
    ),
    "nameless project": (
        "pyproject.toml",
        'name = "shop"',
        'version = "1"',
        r"Could not infer project name in .*pyproject\.toml",
    ),
    "no pyproject": (
        "pyproject.toml",
        None,
        None,
        r"Could not find .*pyproject\.toml",
    ),
    "no app.py": ("app.py", None, None, "cannot find module app"),
}


@pytest.mark.parametrize(
    ("name", "old", "new", "message"), FAILURES.values(), ids=FAILURES
)
def test_what_cannot_be_read_without_running_the_code_fails(
    service: Path, name: str, old: str | None, new: str | None, message: str
):
    if old is None or new is None:
        (service / name).unlink()
    else:
        replace(service, name, old, new)

    with pytest.raises(PolicySourceError, match=message):
        ServiceSource(service).routes()


EDGE_FILES = {
    "pyproject.toml": """
        [tool.poetry]
        name = "edge"
    """,
    "app.py": """
        from fastloom.launcher.schemas import App

        from edge.routing import listing

        app = App(
            routes=listing,
            mounts=[
                ("/api/edge/static", object()),
                ("/api/edge-extra", object()),
            ],
        )
    """,
    "edge/__init__.py": "",
    "edge/paths.py": """
        from enum import Enum, StrEnum


        class Path(StrEnum):
            REPORTS = "/reports"


        class Legacy(str, Enum):
            CHAIN = "/chain"


        class Prefix(str, Enum):
            SPREAD = "/spread"
    """,
    "edge/routing.py": """
        from .api import chain, reports, spread
        from .api.users import router as users_router
        from .paths import Legacy, Path, Prefix

        listing = [
            (users_router, "/users", "Users"),
            (reports.router, Path.REPORTS, "Reports"),
            (chain.top, Legacy.CHAIN, "Chain"),
            (spread.router, Prefix.SPREAD, "Spread"),
        ]
    """,
    "edge/api/__init__.py": "",
    "edge/api/users.py": """
        from fastapi import APIRouter

        router = APIRouter()
        sessions = APIRouter(prefix="/sessions")
        router.include_router(sessions)


        @router.get(path="/me")
        @router.get("/self")
        async def me(): ...


        @sessions.delete("/{session_id}")
        async def end_session(session_id: str): ...
    """,
    "edge/api/reports.py": """
        from fastapi import APIRouter

        router = APIRouter()


        @router.websocket("/live")
        async def live(): ...
    """,
    "edge/api/chain.py": """
        from fastapi import APIRouter

        top = APIRouter(prefix="/top")
        middle = APIRouter(prefix="/middle")
        bottom = APIRouter(prefix="/bottom")
        side = APIRouter()
        middle.include_router(bottom, prefix="/b")
        middle.include_router(bottom, prefix="/b")
        top.include_router(middle, prefix="/m")
        top.include_router(router=side, prefix="/side")


        @bottom.get("/leaf")
        async def leaf(): ...


        @side.get("/")
        async def side_root(): ...
    """,
    "edge/api/spread/__init__.py": """
        from fastapi import APIRouter

        router = APIRouter(prefix="/s")

        from . import handlers, more
    """,
    "edge/api/spread/handlers.py": """
        from . import router


        @router.trace("/trace")
        async def trace(): ...


        if True:

            @router.get("/conditional")
            async def conditional(): ...


        class Views:
            @router.patch("/in-class")
            async def in_class(self): ...


        async def called(): ...


        router.get("/called")(called)


        @router.api_route("/tuple", methods=("GET", "POST"))
        async def tuple_methods(): ...


        @router.api_route("/set", methods={"delete"})
        async def set_methods(): ...
    """,
    "edge/api/spread/more.py": """
        from . import router as spread

        same = spread


        @spread.put("/aliased")
        async def aliased(): ...


        @same.post("/assigned")
        async def assigned(): ...
    """,
}


def test_routes_resolve_across_modules_aliases_and_nesting(tmp_path: Path):
    assert read(write(tmp_path / "edge", EDGE_FILES)) == {
        ("GET", "/api/edge/users/me"),
        ("GET", "/api/edge/users/self"),
        ("DELETE", "/api/edge/users/sessions/{session_id}"),
        ("GET", "/api/edge/reports/live"),
        ("GET", "/api/edge/chain/top/m/middle/b/bottom/leaf"),
        ("GET", "/api/edge/chain/top/side/"),
        ("TRACE", "/api/edge/spread/s/trace"),
        ("GET", "/api/edge/spread/s/conditional"),
        ("PATCH", "/api/edge/spread/s/in-class"),
        ("GET", "/api/edge/spread/s/called"),
        ("GET", "/api/edge/spread/s/tuple"),
        ("POST", "/api/edge/spread/s/tuple"),
        ("DELETE", "/api/edge/spread/s/set"),
        ("PUT", "/api/edge/spread/s/aliased"),
        ("POST", "/api/edge/spread/s/assigned"),
        ("*", "/api/edge/static/{path:path}"),
        ("*", "/api/edge/api/edge-extra/{path:path}"),
    }


@pytest.mark.parametrize(
    ("template", "accepted", "rejected"),
    [
        ("/x", ["/x", "/x/"], ["/xY", "/x/y", "/", "/w/x"]),
        ("/x/", ["/x", "/x/"], ["/xY"]),
        ("/x/{id}", ["/x/1", "/x/1/"], ["/x", "/x/", "/x/1/2"]),
        ("/x/{p:path}", ["/x", "/x/", "/x/a", "/x/a/b"], ["/xa", "/y"]),
        ("/n/{id:int}", ["/n/1", "/n/12/"], ["/n/a", "/n/"]),
        ("/", ["/", ""], ["/x"]),
        ("/a.b-c", ["/a.b-c"], ["/aXb-c"]),
        ("/x/{p:path}/y", ["/x/a/b/y", "/x/a/y/"], ["/x/y", "/x/a/z"]),
        ("/m{id}", ["/m1", "/m1/"], ["/m", "/m/1", "/n1"]),
        ("/a/{one}/b/{two}", ["/a/1/b/2"], ["/a/1/b", "/a/1/2/b/3"]),
    ],
)
def test_a_pattern_matches_the_paths_its_route_answers(
    template: str, accepted: list[str], rejected: list[str]
):
    compiled = compile_path(template)[0]

    def requested(path: str) -> bool:
        candidates = {path, path.removesuffix("/"), f"{path}/"}
        return any(compiled.match(c) for c in candidates)

    assert all(requested(path) for path in accepted)
    assert not any(requested(path) for path in rejected)


def run(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["fastloom-policy", *args])
    return cli.main()


def written(root: Path) -> tuple[str, str]:
    return render(ServiceSource(root).routes()), COVERAGE


def files(directory: Path) -> tuple[str, str]:
    return (
        (directory / ROUTES_FILE).read_text(),
        (directory / COVERAGE_FILE).read_text(),
    )


@pytest.mark.parametrize(
    "args", [[], ["--policy-dir", "rules"]], ids=["default", "moved"]
)
def test_the_command_writes_the_policy_until_it_is_current(
    service: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
):
    directory = service / (args[-1] if args else "policy")

    assert run(monkeypatch, *args) == 1
    assert "was regenerated" in capsys.readouterr().out
    assert files(directory) == written(service)
    assert run(monkeypatch, *args) == 0
    assert capsys.readouterr().out == ""
    assert not (service / ("policy" if args else "rules")).exists()


@pytest.mark.parametrize(
    ("name", "old", "new"),
    [
        ("shop/api/hooks.py", '@router.post("/webhook")', '@router.put("/x")'),
        (f"policy/{COVERAGE_FILE}", "package policy_test", "package stale"),
    ],
    ids=["route changed", "coverage edited"],
)
def test_a_change_regenerates_the_policy(
    service: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    name: str,
    old: str,
    new: str,
):
    run(monkeypatch)
    replace(service, name, old, new)
    capsys.readouterr()

    assert run(monkeypatch) == 1
    assert "was regenerated" in capsys.readouterr().out
    assert files(service / "policy") == written(service)


def test_an_unreadable_source_fails_without_writing(
    service: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    replace(service, "shop/api/admin.py", "STATS)", 'f"/{STATS}")')

    assert run(monkeypatch) == 1
    assert capsys.readouterr().err.startswith("fastloom-policy: ")
    assert not (service / "policy").exists()


GENERATED = (f"policy/{ROUTES_FILE}", f"policy/{COVERAGE_FILE}")
SERVICE_POLICY = """package policy

ruled_routes := {
\t"open": {["GET", "/api/shop/items"], ["*", "/api/shop/files/{path:path}"]},
\t"signed_in": {route | some route in routes} - {
\t\t["GET", "/api/shop/items"],
\t\t["*", "/api/shop/files/{path:path}"],
\t},
}
"""
SERVICE_TESTS = """package service_test

import data.policy

request(method, path) := {"attributes": {"request": {"http": {
\t"method": method,
\t"path": path,
\t"headers": {},
}}}}

get(path) := request("GET", path)

test_a_listed_path_is_requested if {
\tpolicy.requested_group("open") with input as get("/api/shop/items/?a=1")
}

test_a_mount_answers_every_method if {
\tfiles := request("PATCH", "/api/shop/files/a/b")
\tpolicy.requested_group("open") with input as files
}

test_a_sibling_path_is_not_requested if {
\tnot policy.requested_group("open") with input as get("/api/shop/itemsX")
}

test_no_token_is_not_authenticated if {
\tnot policy.authenticated with input as request("GET", "/api/shop/items")
}
"""


@pytest.mark.skipif(shutil.which("opa") is None, reason="opa is not installed")
def test_the_generated_policy_passes_opa(
    service: Path, monkeypatch: pytest.MonkeyPatch
):
    run(monkeypatch)
    (service / "policy" / "service.rego").write_text(SERVICE_POLICY)
    (service / "policy" / "service_test.rego").write_text(SERVICE_TESTS)

    def opa(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["opa", *args], cwd=service, capture_output=True, text=True
        )

    formatted = opa("fmt", "--diff", "--fail", *GENERATED)
    assert (formatted.returncode, formatted.stdout) == (0, "")
    assert opa("check", "--strict", "policy").returncode == 0
    tested = opa("test", "policy")
    assert tested.returncode == 0, tested.stdout

    replace(service, "policy/service.rego", '["GET", "/api/shop/items"], ', "")
    tested = opa("test", "policy")
    assert tested.returncode != 0
    assert "test_every_route_is_ruled: FAIL" in tested.stdout
