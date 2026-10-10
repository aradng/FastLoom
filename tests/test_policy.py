import base64
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from textwrap import dedent

import pytest
from starlette.routing import compile_path

from fastloom.policy import main as cli
from fastloom.policy.rego import ROUTES_FILE, RULES_FILE, RULES_HEADER, render
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


def run(*args: str) -> int:
    code = cli.main.main(list(args), standalone_mode=False)
    return 0 if code is None else code


def rule(method: str, path: str, value: str) -> str:
    return f"\nroute_rules[{json.dumps([method, path])}] := {value}\n"


def rule_all(service: Path, **values: str) -> None:
    write(
        service,
        {
            f"policy/{RULES_FILE}": RULES_HEADER
            + "".join(
                rule(m, p, values.get(p.rsplit("/", 1)[-1], '"public"'))
                for m, p in sorted(SHOP_ROUTES)
            )
        },
    )


@pytest.mark.parametrize(
    "args", [[], ["--policy-dir", "rules"]], ids=["default", "moved"]
)
def test_every_route_gets_a_todo_rule_until_the_service_fills_it(
    service: Path,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
):
    directory = service / (args[-1] if args else "policy")

    assert run(*args) == 1
    assert capsys.readouterr().out.count("added as todo") == len(SHOP_ROUTES)
    assert (directory / ROUTES_FILE).read_text() == render(
        ServiceSource(service).routes()
    )
    assert run(*args) == 1
    assert capsys.readouterr().out.count('not "public"') == len(SHOP_ROUTES)

    replace(service, str(directory / RULES_FILE), '"todo"', '"public"')

    assert run(*args) == 0
    assert capsys.readouterr().out == ""
    assert not (service / ("policy" if args else "rules")).exists()


@pytest.mark.parametrize(
    "value",
    [
        '"authenticated"',
        '[["owner:read", "admin:write"], ["admin"]]',
        '[\n\t["owner:read", "admin:write"],\n\t["admin"],\n]',
        '[{"owner:read", "admin:write"}, {"admin"}]',
    ],
    ids=["authenticated", "roles", "roles across lines", "roles as sets"],
)
def test_a_well_formed_rule_passes(service: Path, value: str):
    run()
    rule_all(service, stats=value)

    assert run() == 0


PROBLEMS = {
    "todo": ('"todo"', 'not "public"'),
    "typo": ('"publc"', 'not "public"'),
    "no alternatives": ("[]", 'not "public"'),
    "no roles": ("[[]]", 'not "public"'),
    "not a role name": ('[["admin", 1]]', 'not "public"'),
}


@pytest.mark.parametrize(("value", "message"), PROBLEMS.values(), ids=PROBLEMS)
def test_a_malformed_rule_is_reported(
    service: Path,
    capsys: pytest.CaptureFixture[str],
    value: str,
    message: str,
):
    run()
    rule_all(service, stats=value)
    capsys.readouterr()

    assert run() == 1
    assert (
        f"GET /api/shop/admin/v1/stats: {message}" in capsys.readouterr().out
    )


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (rule("GET", "/api/shop/gone", '"public"'), "no longer a route"),
        (rule("GET", "/api/shop/items", '"public"'), "listed more than once"),
    ],
    ids=["stale", "duplicate"],
)
def test_a_rule_that_matches_no_single_route_is_reported(
    service: Path,
    capsys: pytest.CaptureFixture[str],
    extra: str,
    message: str,
):
    run()
    rule_all(service)
    (service / "policy" / RULES_FILE).write_text(
        (service / "policy" / RULES_FILE).read_text() + extra
    )
    capsys.readouterr()

    assert run() == 1
    assert message in capsys.readouterr().out


def test_a_new_route_is_appended_without_touching_existing_rules(
    service: Path,
):
    run()
    rule_all(service, stats='[["admin"]]')
    before = (service / "policy" / RULES_FILE).read_text()
    replace(
        service,
        "shop/api/hooks.py",
        '@router.post("/agent/")',
        '@router.put("/agent/")',
    )

    assert run() == 1
    after = (service / "policy" / RULES_FILE).read_text()
    assert after == before + rule("PUT", "/api/shop/agent/", '"todo"')


def test_an_unreadable_source_fails_without_writing(
    service: Path,
    capsys: pytest.CaptureFixture[str],
):
    replace(service, "shop/api/admin.py", "STATS)", 'f"/{STATS}")')

    assert run() == 1
    assert capsys.readouterr().err.startswith("fastloom-policy: ")
    assert not (service / "policy").exists()


def token(roles: list[str], expires_in: int = 600) -> str:
    def part(data: dict[str, object]) -> str:
        encoded = base64.urlsafe_b64encode(json.dumps(data).encode())
        return encoded.rstrip(b"=").decode()

    claims = {"sub": "u", "roles": roles, "exp": int(time.time()) + expires_in}
    return f"{part({'alg': 'HS256'})}.{part(claims)}.c2ln"


DECISIONS = {
    "public route, no token": ("GET", "/api/shop/items/?a=1", None, True),
    "mount root": ("PATCH", "/api/shop/files", None, True),
    "authenticated, no token": ("DELETE", "/api/shop/items/1", None, False),
    "authenticated": ("DELETE", "/api/shop/items/1", token([]), True),
    "expired token": ("DELETE", "/api/shop/items/1", token([], -60), False),
    "one role of a pair": (
        "GET",
        "/api/shop/admin/v1/stats",
        token(["owner:read"]),
        False,
    ),
    "both roles of a pair": (
        "GET",
        "/api/shop/admin/v1/stats",
        token(["owner:read", "admin:write"]),
        True,
    ),
    "the other alternative": (
        "GET",
        "/api/shop/admin/v1/stats",
        token(["admin"]),
        True,
    ),
    "no such route": ("GET", "/api/shop/itemsX", token(["admin"]), False),
}


@pytest.mark.skipif(shutil.which("opa") is None, reason="opa is not installed")
@pytest.mark.parametrize(
    ("method", "path", "bearer", "allowed"), DECISIONS.values(), ids=DECISIONS
)
def test_the_generated_policy_decides_in_opa(
    service: Path,
    method: str,
    path: str,
    bearer: str | None,
    allowed: bool,
):
    run()
    rule_all(
        service,
        **{
            "{item_id}": '"authenticated"',
            "stats": '[["owner:read", "admin:write"], ["admin"]]',
        },
    )
    headers = {} if bearer is None else {"authorization": f"Bearer {bearer}"}
    request = {"method": method, "path": path, "headers": headers}
    write(
        service,
        {
            "input.json": json.dumps(
                {"attributes": {"request": {"http": request}}}
            )
        },
    )

    def opa(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["opa", *args], cwd=service, capture_output=True, text=True
        )

    assert opa("fmt", "--diff", "--fail", "policy").stdout == ""
    assert opa("check", "--strict", "policy").returncode == 0
    decision = opa(
        "eval",
        "-f",
        "raw",
        "-d",
        "policy",
        "-i",
        "input.json",
        "data.policy.allow",
    )
    assert decision.stdout.strip() == str(allowed).lower()
