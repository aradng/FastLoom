import argparse
import sys
from pathlib import Path

from fastloom.policy.rego import COVERAGE, COVERAGE_FILE, ROUTES_FILE, render
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
    try:
        routes = ServiceSource(Path.cwd()).routes()
    except PolicySourceError as e:
        print(f"fastloom-policy: {e}", file=sys.stderr)
        return 1
    changed = write_if_changed(policy_dir / ROUTES_FILE, render(routes))
    changed |= write_if_changed(policy_dir / COVERAGE_FILE, COVERAGE)
    if not changed:
        return 0
    print(
        f"{policy_dir} was regenerated: put each added route in a "
        f"ruled_routes group, drop the removed ones (git diff {policy_dir}), "
        "then stage it."
    )
    return 1
