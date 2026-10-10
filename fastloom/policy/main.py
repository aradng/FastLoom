import ast
from collections import Counter
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

import click

from fastloom.policy.rego import ROUTES_FILE, read_rules, read_scopes, render
from fastloom.policy.schemas import RULE, Route, ordered
from fastloom.policy.source import PolicySourceError, ServiceSource


class Problem(StrEnum):
    ADDED = "added as todo"
    REMOVED = "no longer a route, its rule was dropped"
    INVALID = 'not "public", "authenticated" or a list of role lists'
    UNUSED = "matches no route"


def describe(route: Route) -> str:
    return f"{route.method} {route.path}"


def once[K](keys: list[K], name: Callable[[K], str]) -> None:
    twice = [key for key, n in Counter(keys).items() if n > 1]
    if twice:
        raise PolicySourceError(f"{ROUTES_FILE} lists {name(twice[0])} twice")


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
        once([line.route for line in lines], describe)
        scope_lines = read_scopes(before)
        once([prefix for prefix, _ in scope_lines], lambda p: f"prefix {p}")
        rules = {line.route: line.value for line in lines}
        scopes = dict(scope_lines)
        after = render(routes, rules, scopes)
    except PolicySourceError as e:
        click.echo(f"fastloom-policy: {e}", err=True)
        raise click.exceptions.Exit(1) from e
    report = {
        Problem.ADDED: [
            describe(r) for r in ordered(set(routes) - set(rules))
        ],
        Problem.REMOVED: [
            describe(r) for r in ordered(set(rules) - set(routes))
        ],
        Problem.INVALID: [
            describe(r) for r in routes if r in rules and invalid(rules[r])
        ]
        + [f"prefix {p}" for p, v in sorted(scopes.items()) if invalid(v)],
        Problem.UNUSED: [
            f"prefix {p}"
            for p in sorted(scopes)
            if not any(f"{r.path}/".startswith(f"{p}/") for r in routes)
        ],
    }
    if after != before:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(after, encoding="utf-8")
    for problem, found in report.items():
        for item in found:
            click.echo(f"  {item}: {problem}")
    if after != before or report[Problem.INVALID] or report[Problem.UNUSED]:
        click.echo(f"{path} needs attention: fill each rule, then stage it.")
        raise click.exceptions.Exit(1)
