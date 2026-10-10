import ast
from collections import Counter
from pathlib import Path

import click

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


@click.command(
    help=(
        "Generate the OPA route list for a service and keep its per-route "
        "rules complete, without importing the service."
    )
)
@click.option(
    "--policy-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("policy"),
    show_default=True,
)
def main(policy_dir: Path) -> None:
    rules_path = policy_dir / RULES_FILE
    text = rules_path.read_text() if rules_path.exists() else RULES_HEADER
    try:
        routes = ServiceSource(Path.cwd()).routes()
        rules = read_rules(text)
    except (PolicySourceError, ValueError) as e:
        click.echo(f"fastloom-policy: {e}", err=True)
        raise click.exceptions.Exit(1) from e
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
            click.echo(f"  {route.method} {route.path}: {problem}")
    if changed or any(report.values()):
        click.echo(
            f"{policy_dir} needs attention: fix {rules_path}, then stage it."
        )
        raise click.exceptions.Exit(1)
