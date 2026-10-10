import json

from starlette.routing import compile_path

from fastloom.policy.schemas import Route

ROUTES_FILE = "routes.rego"
RULES_FILE = "rules.rego"
RULE_PREFIX = "route_rules["
RULES_HEADER = "package policy\n"

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

routes := {route | some route, _ in route_patterns}

requested(route) if {
\troute[0] in {http.method, "*"}
\tsome candidate in {path, trim_suffix(path, "/"), concat("", [path, "/"])}
\tregex.match(route_patterns[route], candidate)
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
\t\tpermits(route_rules[route])
\t}
}"""


def key(route: Route) -> str:
    return json.dumps([route.method, route.path], ensure_ascii=False)


def render(routes: list[Route]) -> str:
    patterns = "".join(
        f"\t{key(r)}: `{compile_path(r.path)[0].pattern}`,\n" for r in routes
    )
    listing = f"{{\n{patterns}}}" if routes else "{}"
    return f"{PREAMBLE}\n\nroute_patterns := {listing}\n"


def placeholder(route: Route) -> str:
    return f'\n{RULE_PREFIX}{key(route)}] := "todo"\n'


def read_rules(text: str) -> list[tuple[Route, str]]:
    return [
        read_rule(chunk) for chunk in f"\n{text}".split(f"\n{RULE_PREFIX}")[1:]
    ]


def read_rule(chunk: str) -> tuple[Route, str]:
    head, _, value = chunk.partition("] := ")
    method, path = json.loads(head)
    return Route(method=method, path=path), value.strip()
