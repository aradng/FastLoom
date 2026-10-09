import argparse
import sys
from pathlib import Path

from fastloom.policy.rego import COVERAGE, read_routes, render
from fastloom.policy.source import PolicySourceError
from fastloom.policy.source import read_routes as read_service_routes

ROUTES_FILE = "routes.rego"
COVERAGE_FILE = "routes_test.rego"


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
    target = policy_dir / ROUTES_FILE
    try:
        routes = read_service_routes(Path.cwd())
    except PolicySourceError as e:
        print(f"fastloom-policy: {e}", file=sys.stderr)
        return 1
    before = read_routes(target.read_text()) if target.exists() else set()
    after = {(r.method, r.path) for r in routes}
    changed = write_if_changed(target, render(routes))
    changed |= write_if_changed(policy_dir / COVERAGE_FILE, COVERAGE)
    if not changed:
        return 0
    for method, path in sorted(after - before, key=lambda k: (k[1], k[0])):
        print(f"  + {method} {path}")
    for method, path in sorted(before - after, key=lambda k: (k[1], k[0])):
        print(f"  - {method} {path}")
    print(
        f"{policy_dir} was regenerated: put each added route in a "
        "ruled_routes group, drop the removed ones, then stage it."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
