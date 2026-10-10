import json

from starlette.routing import compile_path

from fastloom.policy.schemas import (
    PREFIX_ADAPTER,
    PolicySourceError,
    Route,
    RuleLine,
    ScopeLine,
)

ROUTES_FILE = "routes.rego"
PATTERN_PREFIX = "route_patterns["
RULE_PREFIX = "route_rules["
SCOPE_PREFIX = "prefix_rules["
STATEMENTS = (PATTERN_PREFIX, RULE_PREFIX, SCOPE_PREFIX)
TODO = '"todo"'
INDENTED = ("\t", " ", "]", "}")

PREAMBLE = """package policy

import rego.v1

http := input.attributes.request.http

path := urlquery.decode(replace(split(http.path, "?")[0], "+", "%2B"))

bearer := substring(http.headers.authorization, count("Bearer "), -1) if \
startswith(lower(http.headers.authorization), "bearer ")

claims := payload if [_, payload, _] := io.jwt.decode(bearer)

authenticated if {
\tis_string(claims.sub)
\tclaims.sub != ""
\tclaims.exp * 1000000000 > time.now_ns()
}

roles := object.get(claims, "roles", [])

routes := {route | some route, _ in data.policy.route_patterns}

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


def key(route: Route) -> str:
    return json.dumps([route.method, route.path], ensure_ascii=False)


def pattern(route: Route) -> str:
    try:
        return compile_path(route.path)[0].pattern
    except AssertionError as e:
        raise PolicySourceError(f"{route.path}: {e}") from e


def block(route: Route, rule: str) -> str:
    return (
        f"\n{PATTERN_PREFIX}{key(route)}] := `{pattern(route)}`\n"
        f"{RULE_PREFIX}{key(route)}] := {rule}\n"
    )


def render(
    routes: list[Route], rules: dict[Route, str], scopes: dict[str, str]
) -> str:
    return (
        PREAMBLE
        + "".join(
            f"\n{SCOPE_PREFIX}{json.dumps(prefix, ensure_ascii=False)}] := "
            f"{rule}\n"
            for prefix, rule in sorted(scopes.items())
        )
        + "".join(block(route, rules.get(route, TODO)) for route in routes)
    )


def split(text: str) -> list[str]:
    lines = text.split("\n")
    first = next(
        (i for i, line in enumerate(lines) if line.startswith(STATEMENTS)),
        len(lines),
    )
    found: list[list[str]] = []
    current: list[str] | None = None
    for number, line in enumerate(lines[first:], first + 1):
        if line.startswith(STATEMENTS):
            current = [line]
            found.append(current)
        elif line.strip() == "":
            current = None
        elif current is not None and line.startswith(INDENTED):
            current.append(line)
        else:
            raise PolicySourceError(
                f"{ROUTES_FILE}:{number}: {line.strip()} is not part of a "
                "rule; keep other rego in its own file"
            )
    return ["\n".join(statement) for statement in found]


def read(text: str) -> tuple[list[RuleLine], list[ScopeLine]]:
    found = split(text)
    return (
        [read_rule(s) for s in found if s.startswith(RULE_PREFIX)],
        [read_scope(s) for s in found if s.startswith(SCOPE_PREFIX)],
    )


def read_rule(statement: str) -> RuleLine:
    head, _, value = statement.removeprefix(RULE_PREFIX).partition("] := ")
    try:
        method, path = json.loads(head)
        return RuleLine(route=Route(method=method, path=path), value=value)
    except ValueError as e:
        raise PolicySourceError(
            f"{ROUTES_FILE}: cannot read the route in {RULE_PREFIX}{head}]"
        ) from e


def read_scope(statement: str) -> ScopeLine:
    head, _, value = statement.removeprefix(SCOPE_PREFIX).partition("] := ")
    try:
        return ScopeLine(
            prefix=PREFIX_ADAPTER.validate_json(head), value=value
        )
    except ValueError as e:
        raise PolicySourceError(
            f"{ROUTES_FILE}: cannot read the prefix in {SCOPE_PREFIX}{head}]"
        ) from e
