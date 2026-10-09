import argparse
import sys
from pathlib import Path

from fastloom.policy.rego import read_access, render
from fastloom.policy.source import PolicySourceError, read_routes

ROUTES_FILE = "routes.rego"


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="fastloom-policy",
        description=(
            "Generate the OPA rules for a service's routes from its role "
            "guards, without importing the service."
        ),
    )
    parser.add_argument("--policy-dir", type=Path, default=Path("policy"))
    target = parser.parse_args().policy_dir / ROUTES_FILE
    try:
        routes = read_routes(Path.cwd())
    except PolicySourceError as e:
        print(f"fastloom-policy: {e}", file=sys.stderr)
        return 1
    content = render(routes)
    existing = target.read_text() if target.exists() else None
    if existing == content:
        return 0
    before = read_access(existing) if existing is not None else {}
    after = {(r.method, r.path): r.access for r in routes}
    for method, path in sorted(
        before.keys() | after.keys(), key=lambda key: (key[1], key[0])
    ):
        if before.get((method, path)) != after.get((method, path)):
            print(
                f"  {method} {path}: {before.get((method, path), '-')}"
                f" -> {after.get((method, path), '-')}"
            )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    print(
        f"{target} was regenerated: review it against your rules, "
        "then stage it."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
