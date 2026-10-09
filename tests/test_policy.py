from pathlib import Path
from textwrap import dedent

import pytest

from fastloom.policy import main as cli
from fastloom.policy.rego import pattern, read_access, render
from fastloom.policy.source import PolicySourceError, read_routes

FILES = {
    "pyproject.toml": """
        [project]
        name = "shop"
    """,
    "app.py": """
        from fastloom.launcher.schemas import App

        from shop.api import admin, hooks, items

        routes = [
            (items.router, "/items", "Items"),
            (admin.router, "/admin", "Admin"),
            (hooks.router, "", "Hooks"),
        ]

        app = App(routes=routes)
    """,
    "shop/__init__.py": "",
    "shop/api/__init__.py": "",
    "shop/roles.py": """
        from enum import StrEnum

        SUPPORT = "SUPPORT"


        class Role(StrEnum):
            ADMIN = "ADMIN"
            SEED = "SEED"
            MEMBER = "MEMBER"
    """,
    "shop/api/deps.py": """
        from typing import Annotated

        from fastapi import Depends

        from settings import TC


        async def signed_in(
            claims: Annotated[dict, Depends(TC.auth.get_claims)],
        ):
            return claims
    """,
    "shop/api/items.py": """
        from typing import Annotated

        from fastapi import APIRouter, Depends
        from fastloom.auth.roles import and_role, or_role

        from settings import TC
        from shop.api.deps import signed_in
        from shop.roles import SUPPORT, Role

        router = APIRouter()


        @router.get("")
        async def list_items(claims=Depends(signed_in)): ...


        @router.delete(
            "/{item_id}",
            dependencies=[
                Depends(
                    TC.auth.require_roles(
                        or_role(and_role(Role.ADMIN, Role.SEED), Role.MEMBER)
                    )
                )
            ],
        )
        async def delete_item(item_id: str): ...


        @router.api_route(
            "/{item_id}/notes/{rest:path}", methods=["GET", "PUT"]
        )
        async def notes(
            token: Annotated[str, Depends(TC.auth.get_token)],
        ): ...


        @router.post(
            "/support",
            dependencies=[Depends(TC.auth.require_roles(SUPPORT))],
        )
        async def support(): ...
    """,
    "shop/api/admin.py": """
        from fastapi import APIRouter, Depends

        from settings import TC

        router = APIRouter(
            prefix="/v1",
            dependencies=[Depends(TC.auth.require_roles("ADMIN"))],
        )


        @router.get(
            "/stats",
            dependencies=[Depends(TC.auth.require_roles("!TRIAL"))],
        )
        async def stats(): ...
    """,
    "shop/api/hooks.py": """
        from typing import Annotated

        from fastapi import APIRouter, Depends

        from settings import TC

        router = APIRouter()


        @router.post("/webhook")
        async def webhook(): ...


        @router.get("/maybe")
        async def maybe(
            claims: Annotated[dict, Depends(TC.optional_auth.get_claims)],
        ): ...
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


def _access(service: Path) -> dict[tuple[str, str], str]:
    return {(r.method, r.path): r.access for r in read_routes(service)}


def test_every_route_is_read_with_the_access_its_guards_need(service: Path):
    assert _access(service) == {
        ("GET", "/api/shop/admin/v1/stats"): "ADMIN&!TRIAL",
        ("GET", "/api/shop/items"): "user",
        ("POST", "/api/shop/items/support"): "SUPPORT",
        ("DELETE", "/api/shop/items/{item_id}"): "(ADMIN&SEED)|MEMBER",
        ("GET", "/api/shop/items/{item_id}/notes/{rest:path}"): "user",
        ("PUT", "/api/shop/items/{item_id}/notes/{rest:path}"): "user",
        ("GET", "/api/shop/maybe"): "open",
        ("POST", "/api/shop/webhook"): "open",
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
            'require_roles("ADMIN")',
            'require_roles(f"{1}")',
            "f-string",
        ),
        (
            "shop/api/hooks.py",
            "router = APIRouter()\n",
            "router = APIRouter()\nrouter.include_router(APIRouter())\n",
            "include_router",
        ),
        (
            "shop/api/items.py",
            "claims=Depends(signed_in)",
            "claims=Depends(signed_in())",
            "dependency returned by signed_in()",
        ),
        (
            "shop/api/admin.py",
            'dependencies=[Depends(TC.auth.require_roles("ADMIN"))]',
            "dependencies=GUARDS",
            "literal list",
        ),
    ],
)
def test_what_cannot_be_read_without_running_the_code_fails(
    service: Path, name: str, old: str, new: str, message: str
):
    _replace(service, name, old, new)

    with pytest.raises(PolicySourceError, match=message):
        read_routes(service)


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


def test_the_rendered_access_table_reads_back(service: Path):
    routes = read_routes(service)

    assert read_access(render(routes)) == _access(service)


def test_a_negated_role_is_checked_against_a_default_of_no_roles(
    service: Path,
):
    rego = render(read_routes(service))

    assert 'roles := object.get(claims, "roles", [])' in rego
    assert 'not "TRIAL" in roles' in rego


def test_the_command_writes_the_rules_then_passes_until_a_guard_changes(
    service: Path, capsys: pytest.CaptureFixture[str]
):
    assert cli.main() == 1
    assert (service / "policy/routes.rego").exists()
    assert cli.main() == 0
    capsys.readouterr()

    _replace(
        service,
        "shop/api/hooks.py",
        "async def webhook(): ...",
        "async def webhook(claims=Depends(TC.auth.get_claims)): ...",
    )

    assert cli.main() == 1
    assert "POST /api/shop/webhook: open -> user" in capsys.readouterr().out
