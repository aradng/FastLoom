import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from textwrap import dedent

import pytest
from fastapi import FastAPI

from fastloom.healthcheck.handler import init_healthcheck
from fastloom.policy import main as cli
from fastloom.policy.rego import ROUTES_FILE, key, render
from fastloom.policy.schemas import PolicySourceError, Route
from fastloom.policy.source import ServiceSource
from fastloom.test.utils import generate_token

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


        @router.get("/special")
        async def special(): ...


        @router.get("/{item_id}")
        async def item(item_id: str): ...


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


        @router.get("/a+b")
        async def plus(): ...
    """,
}


FRAMEWORK = {
    ("GET", "/healthcheck"),
    ("GET", "/tenant_schema"),
    ("GET", "/tenant_settings"),
    ("POST", "/tenant_settings"),
    ("GET", "/reload"),
    ("GET", "/docs"),
    ("GET", "/docs/oauth2-redirect"),
    ("GET", "/redoc"),
    ("GET", "/openapi.json"),
}
CAPABILITIES = {
    "MCPSettings": {("*", "/mcp")},
    "RabbitmqSettings": {
        ("GET", "/rabbitapi"),
        ("GET", "/rabbitapi.json"),
        ("GET", "/rabbitapi.yaml"),
        ("POST", "/rabbitapi/try"),
    },
    "KafkaSettings": {
        ("GET", "/kafkaapi"),
        ("GET", "/kafkaapi.json"),
        ("GET", "/kafkaapi.yaml"),
        ("POST", "/kafkaapi/try"),
    },
}


def framework(prefix: str, *capabilities: str) -> set[tuple[str, str]]:
    return {
        (method, prefix + path)
        for method, path in FRAMEWORK.union(
            *(CAPABILITIES[name] for name in capabilities)
        )
    }


SHOP_ROUTES = framework("/api/shop") | {
    ("GET", "/api/shop/items"),
    ("GET", "/api/shop/items/special"),
    ("GET", "/api/shop/items/{item_id}"),
    ("DELETE", "/api/shop/items/{item_id}"),
    ("GET", "/api/shop/items/{item_id}/notes/{rest:path}"),
    ("PUT", "/api/shop/items/{item_id}/notes/{rest:path}"),
    ("GET", "/api/shop/admin/v1/stats"),
    ("GET", "/api/shop/chart"),
    ("GET", "/api/shop/chart/dashboard/boards/{board_id}"),
    ("POST", "/api/shop/webhook"),
    ("POST", "/api/shop/agent/"),
    ("GET", "/api/shop/a+b"),
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


def test_an_app_without_routes_has_only_fastloom_routes(service: Path):
    write(service, {"app.py": "from x import App\n\napp = App()\n"})

    assert read(service) == framework("/api/shop")


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
    "keywords unpacked": (
        "shop/api/chart/__init__.py",
        'prefix="/dashboard")',
        '**{"prefix": "/dashboard"})',
        r"include_router\(dashboard\.router, \*\*",
    ),
    "App keywords unpacked": (
        "app.py",
        "app = App(",
        "app = App(**EXTRA, ",
        r"App\(\*\*EXTRA",
    ),
    "arguments unpacked": (
        "shop/api/hooks.py",
        '@router.post("/webhook")',
        "@router.post(*PATHS)",
        r"router\.post\(\*PATHS\)",
    ),
    "unknown method": (
        "shop/api/items.py",
        'methods=["GET", "PUT"]',
        'methods=["GET", "FETCH"]',
        "FETCH is not an HTTP method",
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
    "attribute of a constant": (
        "shop/api/admin.py",
        "@router.get(STATS)",
        "@router.get(STATS.name)",
        r"cannot read STATS\.name",
    ),
    "router includes itself": (
        "shop/api/chart/__init__.py",
        "router.include_router(dashboard.router",
        "router.include_router(router",
        "includes itself",
    ),
    "import above the top package": (
        "app.py",
        "from fastloom.launcher.schemas import App\n",
        "from fastloom.launcher.schemas import App\nfrom .. import nothing\n",
        r"cannot resolve from \.\. import nothing",
    ),
}


@pytest.mark.parametrize(
    ("name", "old", "new", "message"), FAILURES.values(), ids=FAILURES
)
def test_what_cannot_be_read_without_running_the_code_fails(
    service: Path, name: str, old: str, new: str, message: str
):
    replace(service, name, old, new)

    with pytest.raises(PolicySourceError, match=message):
        ServiceSource(service).routes()


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("pyproject.toml", None, r"Could not find .*pyproject\.toml"),
        ("app.py", None, "cannot find module app"),
        (
            "pyproject.toml",
            "[project]\n",
            r"Could not infer project name in .*pyproject\.toml",
        ),
    ],
    ids=["no pyproject", "no app.py", "nameless project"],
)
def test_a_missing_entry_file_fails(
    service: Path, name: str, content: str | None, message: str
):
    if content is None:
        (service / name).unlink()
    else:
        write(service, {name: content})

    with pytest.raises(PolicySourceError, match=message):
        ServiceSource(service).routes()


EDGE_FILES = {
    "pyproject.toml": """
        [tool.poetry]
        name = "edge"
    """,
    "app.py": """
        from fastloom.launcher.schemas import App

        from edge.routing import listing, mounted

        app = App(routes=listing, mounts=mounted)
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
        import edge.api.misc
        import edge.api.package.child

        from .api import chain, reports, spread
        from .api.users import router as users_router
        from .paths import Legacy, Path, Prefix

        listing = (
            (users_router, "/users", "Users"),
            (reports.router, Path.REPORTS, "Reports"),
            (chain.top, Legacy.CHAIN.value, "Chain"),
            (spread.router, Prefix.SPREAD, "Spread"),
            (edge.api.misc.router, "/m", "Misc"),
        )
        mounted = (
            ("/api/edge/static", object()),
            ("/api/edge-extra", object()),
            ("", object()),
            ("/api/edge", object()),
        )
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


        @router.head("/live")
        @router.options("/سلام")
        async def probe(): ...
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
    "edge/api/package/__init__.py": """
        from edge.api.spread import router


        @router.get("/package")
        async def package(): ...
    """,
    "edge/api/package/child.py": "",
    "edge/api/misc.py": (
        "import fastapi\n\n"
        'router = fastapi.APIRouter(prefix="/z")\n'
        "later: fastapi.APIRouter\n\n\n"
        "class Holder:\n"
        '    router = fastapi.APIRouter(prefix="/shadow")\n\n\n'
        "def register():\n"
        '    @router.get("/inside")\n'
        "    async def inside(): ...\n\n\n"
        '@router.get("/misc")\n'
        "async def misc(): ...\n"
    ),
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
        ("HEAD", "/api/edge/reports/live"),
        ("OPTIONS", "/api/edge/reports/سلام"),
        ("GET", "/api/edge/spread/s/package"),
        ("GET", "/api/edge/m/z/misc"),
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
        ("*", "/api/edge/{path:path}"),
    } | framework("/api/edge")


SETTINGS_IMPORTS = (
    "import fastloom.mcp.settings as mcp\n"
    "from fastloom.settings.general import BaseGeneralSettings\n"
    "from fastloom.signals.kafka.settings import KafkaSettings\n"
    "from fastloom.signals.rabbit.settings import RabbitmqSettings\n\n\n"
)
CAPABLE = {
    "plain": ("class Settings(BaseGeneralSettings): ...\n", ()),
    "mcp through a module": (
        "class Settings(BaseGeneralSettings, mcp.MCPSettings): ...\n",
        ("MCPSettings",),
    ),
    "brokers": (
        "class Settings(KafkaSettings, RabbitmqSettings): ...\n",
        ("KafkaSettings", "RabbitmqSettings"),
    ),
    "inherited": (
        "class Common(KafkaSettings): ...\n\n\nclass Settings(Common): ...\n",
        ("KafkaSettings",),
    ),
    "only Settings counts": (
        "class TenantSettings(mcp.MCPSettings): ...\n\n\n"
        "class Settings(BaseGeneralSettings): ...\n",
        (),
    ),
}


@pytest.mark.parametrize(
    ("code", "capabilities"), CAPABLE.values(), ids=CAPABLE
)
def test_fastloom_routes_follow_the_settings_capabilities(
    service: Path, code: str, capabilities: tuple[str, ...]
):
    write(service, {"settings.py": SETTINGS_IMPORTS + code})

    assert read(service) == SHOP_ROUTES | framework("/api/shop", *capabilities)


def test_an_unreadable_settings_base_fails(service: Path):
    write(service, {"settings.py": "class Settings(make_base()): ...\n"})

    with pytest.raises(PolicySourceError, match="cannot read the base class"):
        ServiceSource(service).routes()


def test_fastloom_routes_match_what_fastapi_and_fastloom_register():
    app = FastAPI()
    init_healthcheck(app, [])

    assert {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set()) - {"HEAD"}
    } <= FRAMEWORK


def run(*args: str) -> int:
    code = cli.main.main(list(args), standalone_mode=False)
    return 0 if code is None else code


STATS = ("GET", "/api/shop/admin/v1/stats")
ITEMS = ("GET", "/api/shop/items")
ITEM = ("GET", "/api/shop/items/{item_id}")
SPECIAL = ("GET", "/api/shop/items/special")
DELETE_ITEM = ("DELETE", "/api/shop/items/{item_id}")
NOTES = ("GET", "/api/shop/items/{item_id}/notes/{rest:path}")


def rule(method: str, path: str, value: str) -> str:
    return f"route_rules[{key(Route(method=method, path=path))}] := {value}\n"


def scope(prefix: str, value: str) -> str:
    key = json.dumps(prefix, ensure_ascii=False)
    return f"prefix_rules[{key}] := {value}\n"


def append(routes: Path, line: str) -> None:
    routes.write_text(routes.read_text() + "\n" + line)


def rule_all(service: Path, values: dict[tuple[str, str], str | None]) -> Path:
    run()
    routes = service / "policy" / ROUTES_FILE
    text = routes.read_text()
    for method, path in SHOP_ROUTES:
        value = values.get((method, path), '"public"')
        text = text.replace(
            rule(method, path, '"todo"'),
            "" if value is None else rule(method, path, value),
        )
    routes.write_text(text)
    return routes


@pytest.mark.parametrize(
    "args", [[], ["--policy-dir", "rules"]], ids=["default", "moved"]
)
def test_every_route_gets_a_todo_rule_until_the_service_fills_it(
    service: Path, capsys: pytest.CaptureFixture[str], args: list[str]
):
    directory = args[-1] if args else "policy"
    routes = service / directory / ROUTES_FILE

    assert run(*args) == 1
    out = capsys.readouterr().out
    assert out.count("added as todo") == len(SHOP_ROUTES)
    assert 'not "public"' not in out
    assert (
        'route_rules[["DELETE", "/api/shop/items/{item_id}", '
        '"^/api/shop/items/(?P<item_id>[^/]+)$"]] := "todo"\n'
        in routes.read_text()
    )
    assert (
        'route_rules[["*", "/api/shop/files/{path:path}", '
        '"^/api/shop/files/(?P<path>.*)$"]] := "todo"\n' in routes.read_text()
    )
    assert run(*args) == 1
    assert capsys.readouterr().out.count('not "public"') == len(SHOP_ROUTES)

    replace(service, str(routes), '"todo"', '"public"')
    assert run(*args) == 0
    assert capsys.readouterr().out == ""
    written = routes.stat().st_mtime_ns
    assert run(*args) == 0
    assert routes.stat().st_mtime_ns == written
    other = "policy" if args else "rules"
    assert not (service / other).exists()


def test_routes_are_written_in_path_then_method_order(service: Path):
    run()
    keys = [
        tuple(json.loads(head)[:2])
        for head in re.findall(
            r"^route_rules\[(.*?)\] := ",
            (service / "policy" / ROUTES_FILE).read_text(),
            re.MULTILINE,
        )
    ]

    assert keys == sorted(keys, key=lambda k: (k[1], k[0]))


@pytest.mark.parametrize(
    "value",
    [
        '"authenticated"',
        '[["owner:read", "admin:write"], ["admin"]]',
        '[\n\t["owner:read", "admin:write"],\n\t["admin"],\n]',
        '[\n    ["owner:read", "admin:write"],\n    ["admin"],\n]',
        '[{"owner:read", "admin:write"}, {"admin"}]',
        '[{\n\t"admin",\n}]',
    ],
    ids=[
        "authenticated",
        "roles",
        "roles across lines",
        "space indented",
        "roles as sets",
        "set closed on its own line",
    ],
)
def test_a_well_formed_rule_passes_and_survives_the_rewrite(
    service: Path, value: str
):
    routes = rule_all(service, {STATS: value})
    filled = routes.read_text()

    assert run() == 0
    assert routes.read_text() == filled


PROBLEMS = {
    "todo": '"todo"',
    "typo": '"publc"',
    "single quotes": "'public'",
    "no alternatives": "[]",
    "no roles": "[[]]",
    "empty role": '[[""]]',
    "not a role name": '[["admin", 1]]',
    "python tuple": '[("admin",)]',
    "set of sets": '{{"admin"}}',
    "rego syntax": '[["admin"]] if x',
    "not a literal": "data.roles",
}


@pytest.mark.parametrize("value", PROBLEMS.values(), ids=PROBLEMS)
def test_a_malformed_rule_is_reported(
    service: Path, capsys: pytest.CaptureFixture[str], value: str
):
    rule_all(service, {STATS: value})
    capsys.readouterr()

    assert run() == 1
    out = capsys.readouterr().out
    assert 'GET /api/shop/admin/v1/stats: not "public"' in out


def test_a_changed_route_keeps_the_other_rules(
    service: Path, capsys: pytest.CaptureFixture[str]
):
    routes = rule_all(service, {STATS: '[["admin"]]'})
    replace(
        service,
        "shop/api/hooks.py",
        '@router.post("/agent/")',
        '@router.put("/agent/")',
    )
    capsys.readouterr()

    assert run() == 1
    out = capsys.readouterr().out
    assert "PUT /api/shop/agent/: added as todo" in out
    assert "POST /api/shop/agent/: no longer a route" in out
    text = routes.read_text()
    assert rule(*STATS, '[["admin"]]') in text
    assert rule("PUT", "/api/shop/agent/", '"todo"') in text
    assert '"POST", "/api/shop/agent/"' not in text


@pytest.mark.parametrize(
    ("line", "message"),
    [
        (
            rule(*SPECIAL, '"public"'),
            "lists GET /api/shop/items/special twice",
        ),
        (scope("/api/shop", '"public"') * 2, "lists prefix /api/shop twice"),
    ],
    ids=["route", "prefix"],
)
def test_a_line_listed_twice_fails_without_writing(
    service: Path, capsys: pytest.CaptureFixture[str], line: str, message: str
):
    routes = rule_all(service, {})
    append(routes, line)
    edited = routes.read_text()

    assert run() == 1
    assert message in capsys.readouterr().err
    assert routes.read_text() == edited


def test_other_rego_in_the_file_fails_without_writing(
    service: Path, capsys: pytest.CaptureFixture[str]
):
    routes = rule_all(service, {})
    append(routes, "x := 1\n")
    edited = routes.read_text()

    assert run() == 1
    assert "x := 1 is not part of a rule" in capsys.readouterr().err
    assert routes.read_text() == edited


def test_a_rule_cut_by_a_blank_line_fails_without_writing(service: Path):
    routes = rule_all(service, {STATS: '[\n\t["admin"],\n\n\t["owner"],\n]'})
    edited = routes.read_text()

    assert run() == 1
    assert routes.read_text() == edited


def test_an_edited_preamble_is_regenerated(service: Path):
    routes = rule_all(service, {})
    filled = routes.read_text()
    routes.write_text(filled.replace("default allow := false\n", ""))

    assert run() == 1
    assert routes.read_text() == filled


def test_prefix_rules_are_kept_sorted_after_the_preamble(service: Path):
    routes = rule_all(service, {})
    append(routes, scope("/api/shop/items", '[["broker"]]'))
    append(routes, scope("/api/shop/admin", '[["admin"]]'))

    assert run() == 1
    text = routes.read_text()
    assert (
        text.index(scope("/api/shop/admin", '[["admin"]]'))
        < text.index(scope("/api/shop/items", '[["broker"]]'))
        < text.index("\nroute_rules[")
    )
    assert run() == 0


def test_a_non_ascii_prefix_is_kept_as_written(service: Path):
    routes = rule_all(service, {})
    append(routes, scope("/api/shop/سلام", '"authenticated"'))
    run()

    assert scope("/api/shop/سلام", '"authenticated"') in routes.read_text()


@pytest.mark.parametrize(
    ("prefix", "value", "message"),
    [
        ("/api/shop/item", '[["broker"]]', "matches no route"),
        ("/api/shop/items", '"publc"', 'not "public"'),
    ],
    ids=["no route under it", "malformed rule"],
)
def test_a_bad_prefix_rule_fails_once_the_file_is_settled(
    service: Path,
    capsys: pytest.CaptureFixture[str],
    prefix: str,
    value: str,
    message: str,
):
    routes = rule_all(service, {})
    append(routes, scope(prefix, value))
    run()
    capsys.readouterr()

    assert run() == 1
    assert f"prefix {prefix}: {message}" in capsys.readouterr().out


@pytest.mark.parametrize(
    "line",
    [
        'prefix_rules["api/shop"] := "public"\n',
        'prefix_rules[/api/shop] := "public"\n',
        'prefix_rules["/api/shop/{id}"] := "public"\n',
    ],
    ids=["no leading slash", "not a string", "a parameter"],
)
def test_an_unreadable_prefix_fails_without_writing(
    service: Path, capsys: pytest.CaptureFixture[str], line: str
):
    routes = rule_all(service, {})
    append(routes, line)
    edited = routes.read_text()

    assert run() == 1
    assert "cannot read the prefix" in capsys.readouterr().err
    assert routes.read_text() == edited


def test_a_two_line_file_keeps_its_rules(service: Path):
    filled = rule_all(service, {ITEM: '[["admin"]]'}).read_text()
    routes = service / "policy" / ROUTES_FILE
    values = {ITEM: '[["admin"]]'}
    routes.write_text(
        "package policy\n\n"
        + "".join(
            f"route_patterns[{json.dumps(route)}] := `^x$`\n"
            f"route_rules[{json.dumps(route)}] := "
            f"{values.get(route, '"public"')}\n\n"
            for route in SHOP_ROUTES
        )
    )

    assert run() == 1
    assert routes.read_text() == filled
    assert run() == 0


@pytest.mark.parametrize(
    "head",
    ['["GET" "/x"]', '["FETCH", "/x"]', '["GET"]'],
    ids=["not json", "unknown method", "no path"],
)
def test_an_unreadable_rule_fails_without_writing(
    service: Path, capsys: pytest.CaptureFixture[str], head: str
):
    text = f'package policy\n\nroute_rules[{head}] := "public"\n'
    routes = write(service, {f"policy/{ROUTES_FILE}": text}) / "policy"

    assert run() == 1
    assert capsys.readouterr().err.startswith(
        f"fastloom-policy: {ROUTES_FILE}: cannot read"
    )
    assert (routes / ROUTES_FILE).read_text() == text


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("STATS)", 'f"/{STATS}")', "f-string"),
        ("@router.get(STATS)", '@router.get("/{id:foo}")', "path convertor"),
    ],
    ids=["f-string", "unknown convertor"],
)
def test_an_unreadable_source_fails_without_writing(
    service: Path,
    capsys: pytest.CaptureFixture[str],
    old: str,
    new: str,
    message: str,
):
    replace(service, "shop/api/admin.py", old, new)

    assert run() == 1
    err = capsys.readouterr().err
    assert err.startswith("fastloom-policy: ")
    assert message in err
    assert not (service / "policy").exists()


def token(roles: list[str], **claims: object) -> str:
    payload = {
        "sub": "u",
        "roles": roles,
        "exp": int(time.time()) + 600,
    } | claims
    present = {k: v for k, v in payload.items() if v is not None}
    return f"Bearer {generate_token(json.dumps(present))}"


def auth(value: str) -> dict[str, str]:
    return {"authorization": value}


needs_opa = pytest.mark.skipif(
    shutil.which("opa") is None, reason="opa is not installed"
)


def opa(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["opa", *args],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=60,
    )


def assert_allow(
    directory: Path,
    method: str,
    path: str,
    headers: dict[str, str],
    allowed: bool,
) -> None:
    request = {"method": method, "path": path, "headers": headers}
    write(
        directory,
        {
            "input.json": json.dumps(
                {"attributes": {"request": {"http": request}}}
            )
        },
    )
    decision = opa(
        directory,
        "eval",
        "-f",
        "raw",
        "-d",
        "policy",
        "-i",
        "input.json",
        "data.policy.allow",
    )
    assert decision.stdout.strip() == str(allowed).lower(), decision.stderr


@needs_opa
@pytest.mark.parametrize("state", ["todo", "ruled", "prefixed", "no routes"])
def test_the_generated_policy_is_valid_rego(service: Path, state: str):
    if state == "no routes":
        write(service, {"app.py": "from x import App\n\napp = App()\n"})
    run()
    if state in ("ruled", "prefixed"):
        routes = rule_all(service, {STATS: '[["admin"]]'})
    if state == "prefixed":
        append(routes, scope("/api/shop/admin", '[["admin"]]'))
        run()
    write(service, {"policy/custom.rego": CUSTOM})

    assert opa(service, "fmt", "--diff", "--fail", "policy").stdout == ""
    checked = opa(service, "check", "--strict", "policy")
    assert checked.returncode == 0, checked.stdout + checked.stderr
    v0 = opa(service, "check", "--v0-compatible", f"policy/{ROUTES_FILE}")
    assert v0.returncode == 0, v0.stdout + v0.stderr


CUSTOM = 'package policy\n\nallow if http.headers["x-internal-key"] == "k"\n'
RULES: dict[tuple[str, str], str | None] = {
    DELETE_ITEM: '"authenticated"',
    STATS: '[["owner:read", "admin:write"], ["admin"]]',
    ITEM: '[["admin"]]',
}
ITEM_1 = ("DELETE", "/api/shop/items/1")
DECISIONS = {
    "public, no token": ("GET", "/api/shop/items/?a=1", {}, {}, True),
    "mount root": ("PATCH", "/api/shop/files", {}, {}, True),
    "catch-all": ("GET", "/api/shop/items/1/notes/a/b", {}, {}, True),
    "a plus in the path": ("GET", "/api/shop/a+b", {}, {}, True),
    "encoded slash matches the decoded route": (
        "GET",
        "/api/shop/items/1%2Fnotes%2Fx",
        {},
        {ITEM: '"public"', NOTES: '[["admin"]]'},
        False,
    ),
    "malformed escape": ("GET", "/api/shop/items%zz", {}, {}, False),
    "authenticated, no token": (*ITEM_1, {}, {}, False),
    "authenticated": (*ITEM_1, auth(token([])), {}, True),
    "expired": (
        *ITEM_1,
        auth(token([], exp=int(time.time()) - 60)),
        {},
        False,
    ),
    "exp not a number": (*ITEM_1, auth(token([], exp="soon")), {}, False),
    "no exp": (*ITEM_1, auth(token([], exp=None)), {}, False),
    "empty sub": (*ITEM_1, auth(token([], sub="")), {}, False),
    "sub not a string": (*ITEM_1, auth(token([], sub=123)), {}, False),
    "no sub": (*ITEM_1, auth(token([], sub=None)), {}, False),
    "not a bearer": (*ITEM_1, auth("Basic dTpw"), {}, False),
    "lowercase scheme": (
        *ITEM_1,
        auth(token([]).replace("Bearer", "bearer", 1)),
        {},
        True,
    ),
    "the service's own allow": (*ITEM_1, {"x-internal-key": "k"}, {}, True),
    "one role of a pair": (*STATS, auth(token(["owner:read"])), {}, False),
    "both roles of a pair": (
        *STATS,
        auth(token(["owner:read", "admin:write"])),
        {},
        True,
    ),
    "the other alternative": (*STATS, auth(token(["admin"])), {}, True),
    "role on an expired token": (
        *STATS,
        auth(token(["admin"], exp=int(time.time()) - 60)),
        {},
        False,
    ),
    "role without a sub": (
        *STATS,
        auth(token(["admin"], sub=None)),
        {},
        False,
    ),
    "roles as sets": (
        *STATS,
        auth(token(["admin"])),
        {STATS: '[{"owner:read"}, {"admin"}]'},
        True,
    ),
    "overlap, one rule denies": (*SPECIAL, {}, {}, False),
    "overlap, both rules allow": (*SPECIAL, auth(token(["admin"])), {}, True),
    "wrong method": (
        "POST",
        "/api/shop/items",
        auth(token(["admin"])),
        {},
        False,
    ),
    "no such route": (
        "GET",
        "/api/shop/itemsX",
        auth(token(["admin"])),
        {},
        False,
    ),
    "todo rule": (*STATS, auth(token(["admin"])), {STATS: '"todo"'}, False),
    "missing rule": (*STATS, auth(token(["admin"])), {STATS: None}, False),
    "object rule": (
        *STATS,
        auth(token(["admin"])),
        {STATS: '{"x": ["admin"]}'},
        False,
    ),
    "empty alternative": (
        *STATS,
        auth(token(["admin"])),
        {STATS: "[[]]"},
        False,
    ),
}


@needs_opa
@pytest.mark.parametrize(
    ("method", "path", "headers", "overrides", "allowed"),
    DECISIONS.values(),
    ids=DECISIONS,
)
def test_the_generated_policy_decides_in_opa(
    service: Path,
    method: str,
    path: str,
    headers: dict[str, str],
    overrides: dict[tuple[str, str], str | None],
    allowed: bool,
):
    rule_all(service, RULES | overrides)
    write(service, {"policy/custom.rego": CUSTOM})

    assert_allow(service, method, path, headers, allowed)


GUARDED = {
    "route role alone": (
        {"/api/shop/admin": '[["broker"]]'},
        STATS,
        auth(token(["admin"])),
        False,
    ),
    "prefix role alone": (
        {"/api/shop/admin": '[["broker"]]'},
        STATS,
        auth(token(["broker"])),
        False,
    ),
    "both roles": (
        {"/api/shop/admin": '[["broker"]]'},
        STATS,
        auth(token(["broker", "admin"])),
        True,
    ),
    "anonymous under a role prefix": (
        {"/api/shop/items": '[["broker"]]'},
        ITEMS,
        {},
        False,
    ),
    "a role prefix over a public route": (
        {"/api/shop/items": '[["broker"]]'},
        ITEMS,
        auth(token(["broker"])),
        True,
    ),
    "authenticated prefix, no token": (
        {"/api/shop/items": '"authenticated"'},
        ITEMS,
        {},
        False,
    ),
    "authenticated prefix": (
        {"/api/shop/items": '"authenticated"'},
        ITEMS,
        auth(token([])),
        True,
    ),
    "nested prefixes, outer only": (
        {"/api/shop": '"authenticated"', "/api/shop/items": '[["broker"]]'},
        ITEMS,
        auth(token([])),
        False,
    ),
    "nested prefixes": (
        {"/api/shop": '"authenticated"', "/api/shop/items": '[["broker"]]'},
        ITEMS,
        auth(token(["broker"])),
        True,
    ),
    "a sibling name is not under the prefix": (
        {"/api/shop/item": '[["broker"]]'},
        ITEMS,
        {},
        True,
    ),
    "a parameter route under the prefix": (
        {"/api/shop/items/7": '[["broker"]]'},
        ("GET", "/api/shop/items/7"),
        {},
        False,
    ),
}


@needs_opa
@pytest.mark.parametrize(
    ("prefixes", "request_route", "headers", "allowed"),
    GUARDED.values(),
    ids=GUARDED,
)
def test_a_prefix_rule_guards_every_request_under_it_in_opa(
    service: Path,
    prefixes: dict[str, str],
    request_route: tuple[str, str],
    headers: dict[str, str],
    allowed: bool,
):
    routes = rule_all(service, {STATS: '[["admin"]]'})
    for prefix, value in prefixes.items():
        append(routes, scope(prefix, value))

    assert_allow(service, *request_route, headers, allowed)


PATTERNS = [
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
]


@needs_opa
def test_each_route_pattern_matches_the_paths_it_answers(tmp_path: Path):
    def case(index: int, template: str, path: str, expected: bool) -> str:
        route = key(Route(method="GET", path=template))
        request = json.dumps(
            {
                "attributes": {
                    "request": {"http": {"method": "GET", "path": path}}
                }
            }
        )
        negation = "" if expected else "not "
        return (
            f"test_{index} if {{\n\t{negation}policy.requested({route}) "
            f"with input as {request}\n}}\n"
        )

    cases = [
        (template, path, expected)
        for template, accepted, rejected in PATTERNS
        for expected, paths in ((True, accepted), (False, rejected))
        for path in paths
    ]
    write(
        tmp_path,
        {
            f"policy/{ROUTES_FILE}": render(
                [Route(method="GET", path=t) for t, _, _ in PATTERNS], {}, {}
            ),
            "policy/patterns_test.rego": "package patterns_test\n\n"
            "import data.policy\n\n"
            + "\n".join(case(i, *c) for i, c in enumerate(cases)),
        },
    )

    tested = opa(tmp_path, "test", "policy")
    assert tested.returncode == 0, tested.stdout
