import argparse
import asyncio
import json
from pathlib import Path
from string import Template
from typing import Any

HTTP_METHODS = {"get", "put", "post", "delete", "patch", "head", "options"}
MANIFEST_NAME = "routes.json"
COVERAGE_NAME = "fastloom_routes_test.rego"
COVERAGE_TEMPLATE = Path(__file__).with_name("coverage.rego.tmpl")


def access_of(operation: dict[str, Any]) -> str:
    security = operation.get("security")
    if security is None:
        return "open"
    scopes = sorted(
        {
            s
            for requirement in security
            for ss in requirement.values()
            for s in ss
        }
    )
    return "+".join(scopes) or "user"


def manifest(root_path: str, openapi: dict[str, Any]) -> list[dict[str, str]]:
    return sorted(
        (
            {
                "method": method.upper(),
                "path": root_path + path,
                "access": access_of(operation),
            }
            for path, item in openapi["paths"].items()
            for method, operation in item.items()
            if method in HTTP_METHODS
        ),
        key=lambda r: (r["path"], r["method"]),
    )


async def build_openapi() -> tuple[str, dict[str, Any]]:
    from fastloom.launcher.main import app

    fastapi_app = app()
    return fastapi_app.root_path, fastapi_app.openapi()


def write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text() == content:
        return False
    path.write_text(content)
    return True


def report(before: list[dict[str, str]], after: list[dict[str, str]]) -> None:
    old = {(r["method"], r["path"]): r["access"] for r in before}
    new = {(r["method"], r["path"]): r["access"] for r in after}
    for method, path in sorted(old.keys() | new.keys(), key=lambda k: k[::-1]):
        if old.get((method, path)) != new.get((method, path)):
            print(
                f"  {method} {path}: {old.get((method, path), '-')}"
                f" -> {new.get((method, path), '-')}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="fastloom-policy",
        description="Keep a service's OPA policy in step with its routes.",
    )
    parser.add_argument("--package", required=True)
    parser.add_argument("--policy-dir", type=Path, default=Path("policy"))
    args = parser.parse_args()

    manifest_path = args.policy_dir / MANIFEST_NAME
    before = (
        json.loads(manifest_path.read_text())["app_routes"]
        if manifest_path.exists()
        else []
    )
    after = manifest(*asyncio.run(build_openapi()))
    args.policy_dir.mkdir(parents=True, exist_ok=True)
    changed = write_if_changed(
        manifest_path, json.dumps({"app_routes": after}, indent=2) + "\n"
    )
    changed |= write_if_changed(
        args.policy_dir / COVERAGE_NAME,
        Template(COVERAGE_TEMPLATE.read_text()).substitute(
            package=args.package
        ),
    )
    if not changed:
        return 0
    report(before, after)
    print(
        f"{args.policy_dir} was regenerated: rule every changed route in "
        f"package {args.package}'s ruled_routes, then stage the policy dir."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
