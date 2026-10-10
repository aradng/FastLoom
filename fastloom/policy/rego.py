import json
from itertools import takewhile

from starlette.routing import compile_path

from fastloom.policy.schemas import Route, RuleLine
from fastloom.policy.source import PolicySourceError

ROUTES_FILE = "routes.rego"
PATTERN_PREFIX = "route_patterns["
RULE_PREFIX = "route_rules["
TODO = '"todo"'
INDENTED = ("\t", " ", "]", "}")

PREAMBLE = """package policy

http := input.attributes.request.http

path := split(http.path, "?")[0]

bearer := substring(http.headers.authorization, count("Bearer "), -1) if \
startswith(http.headers.authorization, "Bearer ")

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

allow if {
\tcount(matched) > 0
\tevery route in matched {
\t\tpermits(data.policy.route_rules[route])
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


def render(routes: list[Route], rules: dict[Route, str]) -> str:
    return PREAMBLE + "".join(
        block(route, rules.get(route, TODO)) for route in routes
    )


def read_rules(text: str) -> list[RuleLine]:
    return [
        read_rule(chunk) for chunk in f"\n{text}".split(f"\n{RULE_PREFIX}")[1:]
    ]


def read_rule(chunk: str) -> RuleLine:
    first, *rest = chunk.split("\n")
    statement = "\n".join(
        [first, *takewhile(lambda line: line.startswith(INDENTED), rest)]
    )
    head, _, value = statement.partition("] := ")
    try:
        method, path = json.loads(head)
        return RuleLine(route=Route(method=method, path=path), value=value)
    except ValueError as e:
        raise PolicySourceError(
            f"{ROUTES_FILE}: cannot read the route in {RULE_PREFIX}{head}]"
        ) from e
