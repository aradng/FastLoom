import ast
from collections import Counter
from enum import StrEnum
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


class Problem(StrEnum):
    ADDED = "added as todo"
    STALE = "no longer a route, delete it"
    DUPLICATE = "listed more than once"
    INVALID = 'not "public", "authenticated" or a list of role lists'


def write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def invalid(value: str) -> bool:
    if "'" in value:
        return True
    try:
        RULE.validate_python(ast.literal_eval(value), strict=True)
    except (ValueError, SyntaxError, TypeError):
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
    text = (
        rules_path.read_text(encoding="utf-8") if rules_path.exists() else ""
    )
    if text.strip() == "":
        text = RULES_HEADER
    try:
        routes = ServiceSource(Path.cwd()).routes()
        rendered = render(routes)
        rules = read_rules(text)
    except PolicySourceError as e:
        click.echo(f"fastloom-policy: {e}", err=True)
        raise click.exceptions.Exit(1) from e
    listed = Counter(rule.route for rule in rules)
    added = ordered(set(routes) - set(listed))
    report = {
        Problem.ADDED: added,
        Problem.STALE: ordered(set(listed) - set(routes)),
        Problem.DUPLICATE: ordered(r for r, n in listed.items() if n > 1),
        Problem.INVALID: ordered(
            rule.route
            for rule in rules
            if listed[rule.route] == 1 and invalid(rule.value)
        ),
    }
    changed = write_if_changed(policy_dir / ROUTES_FILE, rendered)
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
