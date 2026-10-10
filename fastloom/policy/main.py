import ast
from collections import Counter
from enum import StrEnum
from pathlib import Path

import click

from fastloom.policy.rego import ROUTES_FILE, read_rules, render
from fastloom.policy.schemas import RULE, ordered
from fastloom.policy.source import PolicySourceError, ServiceSource


class Problem(StrEnum):
    ADDED = "added as todo"
    REMOVED = "no longer a route, its rule was dropped"
    INVALID = 'not "public", "authenticated" or a list of role lists'


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
        "Generate a service's OPA routes and keep a rule for each, without "
        "importing the service."
    )
)
@click.option(
    "--policy-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("policy"),
    show_default=True,
)
def main(policy_dir: Path) -> None:
    path = policy_dir / ROUTES_FILE
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        routes = ServiceSource(Path.cwd()).routes()
        lines = read_rules(before)
        twice = [
            r for r, n in Counter(r.route for r in lines).items() if n > 1
        ]
        if twice:
            raise PolicySourceError(
                f"{ROUTES_FILE} lists {twice[0].method} {twice[0].path} twice"
            )
        rules = {line.route: line.value for line in lines}
        after = render(routes, rules)
    except PolicySourceError as e:
        click.echo(f"fastloom-policy: {e}", err=True)
        raise click.exceptions.Exit(1) from e
    report = {
        Problem.ADDED: ordered(set(routes) - set(rules)),
        Problem.REMOVED: ordered(set(rules) - set(routes)),
        Problem.INVALID: ordered(
            r for r in routes if r in rules and invalid(rules[r])
        ),
    }
    if after != before:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(after, encoding="utf-8")
    for problem, found in report.items():
        for route in found:
            click.echo(f"  {route.method} {route.path}: {problem}")
    if after != before or report[Problem.INVALID]:
        click.echo(f"{path} needs attention: fill each rule, then stage it.")
        raise click.exceptions.Exit(1)
