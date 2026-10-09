import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from fastloom.extras import LIBCST_INSTALLED
from fastloom.policy.rego import (
    COVERAGE,
    COVERAGE_FILE,
    ROUTES_FILE,
    listed_routes,
    render,
)
from fastloom.policy.schemas import ordered

if TYPE_CHECKING or LIBCST_INSTALLED:
    from fastloom.policy.source import PolicySourceError, ServiceSource


def write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="fastloom-policy",
        description=(
            "Generate the OPA route list for a service, and the tests that "
            "make its policy rule every route, without importing the service."
        ),
    )
    parser.add_argument("--policy-dir", type=Path, default=Path("policy"))
    policy_dir = parser.parse_args().policy_dir
    if not LIBCST_INSTALLED:
        print(
            "fastloom-policy: libcst is missing, install fastloom[policy]",
            file=sys.stderr,
        )
        return 1
    target = policy_dir / ROUTES_FILE
    try:
        routes = ServiceSource(Path.cwd()).routes()
    except PolicySourceError as e:
        print(f"fastloom-policy: {e}", file=sys.stderr)
        return 1
    before = listed_routes(target.read_text()) if target.exists() else set()
    after = set(routes)
    changed = write_if_changed(target, render(routes))
    changed |= write_if_changed(policy_dir / COVERAGE_FILE, COVERAGE)
    if not changed:
        return 0
    for sign, diff in (("+", after - before), ("-", before - after)):
        for route in ordered(diff):
            print(f"  {sign} {route.method} {route.path}")
    print(
        f"{policy_dir} was regenerated: put each added route in a "
        "ruled_routes group, drop the removed ones, then stage it."
    )
    return 1
