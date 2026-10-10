import json
import re
from collections import defaultdict
from collections.abc import Iterable

from starlette.routing import compile_path

from fastloom.policy.schemas import (
    PREFIX_ADAPTER,
    PolicySourceError,
    Route,
    RuleLine,
    ScopeLine,
)

ROUTES_FILE = "routes.rego"
RULES = "route_rules"
PATTERNS = "route_patterns"
SCOPES = "prefix_rules"
HEAD = re.compile(rf"^({RULES}|{PATTERNS}|{SCOPES})( := {{}}?$|\[)")
STRINGS = re.compile(r'"(?:\\.|[^"\\])*"|`[^`]*`')
TODO = '"todo"'
DECODER = json.JSONDecoder()

PREAMBLE = """package policy

import rego.v1

http := input.attributes.request.http

path := urlquery.decode(replace(split(http.path, "?")[0], "+", "%2B"))

bearer := trim_space(\
substring(http.headers.authorization, count("bearer "), -1)\
) if startswith(lower(http.headers.authorization), "bearer ")

claims := payload if [_, payload, _] := io.jwt.decode(bearer)

authenticated if {
\tis_string(claims.sub)
\tclaims.sub != ""
\tclaims.exp * 1000000000 > time.now_ns()
}

roles := object.get(claims, "roles", [])

routes := {route | some route, _ in data.policy.route_rules}

requested(route) if {
\troute[0] in {http.method, "*"}
\tsome candidate in {path, trim_suffix(path, "/"), concat("", [path, "/"])}
\tregex.match(data.policy.route_patterns[route], candidate)
}

matched := {route | some route in routes; requested(route)}

permits("public")

permits("authenticated") if authenticated

permits(alternatives) if {
\tauthenticated
\tis_array(alternatives)
\tsome needed in alternatives
\tcount(needed) > 0
\tevery role in needed {
\t\trole in roles
\t}
}

default allow := false

slashed_path := concat("", [trim_suffix(path, "/"), "/"])

guards := {rule |
\tsome prefix, rule in data.policy.prefix_rules
\tstartswith(slashed_path, concat("", [prefix, "/"]))
}

allow if {
\tcount(matched) > 0
\tevery route in matched {
\t\tpermits(data.policy.route_rules[route])
\t}
\tevery rule in guards {
\t\tpermits(rule)
\t}
}
"""


def route_key(route: Route) -> str:
    return json.dumps([route.method, route.path], ensure_ascii=False)


def pattern(route: Route) -> str:
    try:
        return compile_path(route.path)[0].pattern
    except AssertionError as e:
        raise PolicySourceError(f"{route.path}: {e}") from e


def table(name: str, entries: Iterable[tuple[str, str]]) -> str:
    lines = "".join(f"\t{key}: {value},\n" for key, value in entries)
    return f"\n{name} := {{\n{lines}}}\n" if lines else ""


def render(
    routes: list[Route], rules: dict[Route, str], scopes: dict[str, str]
) -> str:
    return (
        PREAMBLE
        + table(
            SCOPES,
            (
                (json.dumps(prefix, ensure_ascii=False), rule)
                for prefix, rule in sorted(scopes.items())
            ),
        )
        + table(RULES, ((route_key(r), rules.get(r, TODO)) for r in routes))
        + table(PATTERNS, ((route_key(r), f"`{pattern(r)}`") for r in routes))
    )


def depth(line: str) -> int:
    bare = STRINGS.sub("", line)
    return sum(bare.count(c) for c in "[{(") - sum(
        bare.count(c) for c in "]})"
    )


def statements(text: str) -> dict[str, list[tuple[str, str]]]:
    lines = text.split("\n")
    first = next(
        (i for i, line in enumerate(lines) if HEAD.match(line)), len(lines)
    )
    found: dict[str, list[tuple[str, str]]] = defaultdict(list)
    table: str | None = None
    opened = 0
    current: list[str] = []
    level = 0
    for number, raw in enumerate(lines[first:], first + 1):
        line = raw.rstrip()
        if not current:
            head = HEAD.match(line)
            if not line or (head and head[2] == " := {}"):
                continue
            if line.lstrip().startswith("#") or not (table or head):
                raise PolicySourceError(
                    f"{ROUTES_FILE}:{number}: {line.strip()} is not part "
                    "of a rule; keep other rego in its own file"
                )
            if head and head[2] != "[" or line == "}":
                table, opened = (head[1], number) if head else (None, 0)
                continue
        current.append(line)
        level += depth(line)
        if level > 0:
            continue
        if table:
            found[table].append(entry("\n".join(current).strip()))
        else:
            name, _, statement = "\n\t".join(current).partition("[")
            key, _, value = statement.partition("] := ")
            found[name].append((key, value))
        current, level = [], 0
    if table or current:
        raise PolicySourceError(
            f"{ROUTES_FILE}:{opened or number}: "
            f"{table or current[0].strip()} is never closed"
        )
    return found


def entry(text: str) -> tuple[str, str]:
    try:
        _, end = DECODER.raw_decode(text)
    except ValueError:
        end = 0
    key, value = text[:end], text[end:].lstrip()
    if not value.startswith(":"):
        raise PolicySourceError(f"{ROUTES_FILE}: cannot read {text}")
    return key, value[1:].strip().removesuffix(",").rstrip()


def read(text: str) -> tuple[list[RuleLine], list[ScopeLine]]:
    found = statements(text)
    return (
        [read_rule(*e) for e in found[RULES]],
        [read_scope(*e) for e in found[SCOPES]],
    )


def read_rule(key: str, value: str) -> RuleLine:
    try:
        method, path = json.loads(key)
        return RuleLine(route=Route(method=method, path=path), value=value)
    except (ValueError, TypeError) as e:
        raise PolicySourceError(
            f"{ROUTES_FILE}: cannot read the route {key}"
        ) from e


def read_scope(key: str, value: str) -> ScopeLine:
    try:
        return ScopeLine(prefix=PREFIX_ADAPTER.validate_json(key), value=value)
    except ValueError as e:
        raise PolicySourceError(
            f"{ROUTES_FILE}: cannot read the prefix {key}"
        ) from e
