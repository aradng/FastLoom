from collections import Counter
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

import click

from fastloom.policy.rego import ROUTES_FILE, read, render
from fastloom.policy.schemas import (
    PolicySourceError,
    Route,
    RuleLine,
    ScopeLine,
    ordered,
)
from fastloom.policy.source import ServiceSource


class Problem(StrEnum):
    ADDED = "added as todo"
    REMOVED = "no longer a route, its rule was dropped"
    INVALID = 'not "public", "authenticated" or a list of role lists'
    UNUSED = "matches no route"


FAILURES = (Problem.INVALID, Problem.UNUSED)


def describe(route: Route) -> str:
    return f"{route.method} {route.path}"


def describe_prefix(prefix: str) -> str:
    return f"prefix {prefix}"


def once[K](keys: list[K], name: Callable[[K], str]) -> None:
    twice = [key for key, n in Counter(keys).items() if n > 1]
    if twice:
        raise PolicySourceError(f"{ROUTES_FILE} lists {name(twice[0])} twice")


def report(
    routes: list[Route], rules: list[RuleLine], scopes: list[ScopeLine]
) -> dict[Problem, list[str]]:
    ruled = {line.route for line in rules}
    return {
        Problem.ADDED: [describe(r) for r in routes if r not in ruled],
        Problem.REMOVED: [describe(r) for r in ordered(ruled - set(routes))],
        Problem.INVALID: [
            describe(line.route)
            for line in rules
            if line.route in routes and not line.valid
        ]
        + [describe_prefix(s.prefix) for s in scopes if not s.valid],
        Problem.UNUSED: [
            describe_prefix(s.prefix)
            for s in scopes
            if not any(f"{r.path}/".startswith(f"{s.prefix}/") for r in routes)
        ],
    }


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
        rules, scopes = read(before)
        once([line.route for line in rules], describe)
        once([line.prefix for line in scopes], describe_prefix)
        after = render(
            routes,
            {line.route: line.value for line in rules},
            {line.prefix: line.value for line in scopes},
        )
    except PolicySourceError as e:
        click.echo(f"fastloom-policy: {e}", err=True)
        raise click.exceptions.Exit(1) from e
    found = report(routes, rules, scopes)
    if after != before:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(after, encoding="utf-8")
    for problem, items in found.items():
        for item in items:
            click.echo(f"  {item}: {problem}")
    if after != before or any(found[problem] for problem in FAILURES):
        click.echo(f"{path} needs attention: fill each rule, then stage it.")
        raise click.exceptions.Exit(1)
