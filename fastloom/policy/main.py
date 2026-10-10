import argparse
import ast
import sys
from collections import Counter
from pathlib import Path

from fastloom.policy.rego import (
    ROUTES_FILE,
    RULES_FILE,
    RULES_HEADER,
    placeholder,
    read_rules,
    render,
)
from fastloom.policy.schemas import RULE, ordered
from fastloom.policy.source import PolicySourceError, ServiceSource


def write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


def invalid(value: str) -> bool:
    try:
        RULE.validate_python(ast.literal_eval(value))
    except (ValueError, SyntaxError):
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="fastloom-policy",
        description=(
            "Generate the OPA route list for a service and keep its "
            "per-route rules complete, without importing the service."
        ),
    )
    parser.add_argument("--policy-dir", type=Path, default=Path("policy"))
    policy_dir = parser.parse_args().policy_dir
    rules_path = policy_dir / RULES_FILE
    text = rules_path.read_text() if rules_path.exists() else RULES_HEADER
    try:
        routes = ServiceSource(Path.cwd()).routes()
        rules = read_rules(text)
    except (PolicySourceError, ValueError) as e:
        print(f"fastloom-policy: {e}", file=sys.stderr)
        return 1
    listed = Counter(route for route, _ in rules)
    added = ordered(set(routes) - set(listed))
    report = {
        "added as todo": added,
        "no longer a route, delete it": ordered(set(listed) - set(routes)),
        "listed more than once": ordered(
            r for r, n in listed.items() if n > 1
        ),
        'not "public", "authenticated" or a list of role lists': ordered(
            route for route, value in rules if invalid(value)
        ),
    }
    changed = write_if_changed(policy_dir / ROUTES_FILE, render(routes))
    changed |= write_if_changed(
        rules_path, text + "".join(placeholder(r) for r in added)
    )
    for problem, found in report.items():
        for route in found:
            print(f"  {route.method} {route.path}: {problem}")
    if changed or any(report.values()):
        print(
            f"{policy_dir} needs attention: fix {rules_path}, then stage it."
        )
        return 1
    return 0
