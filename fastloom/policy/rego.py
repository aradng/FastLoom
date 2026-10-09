import json
import re

from fastloom.policy.source import Route

PATH_PARAMETER = re.compile(r"\{[^/}]+\}")
ROUTE_ENTRY = re.compile(r'^\t(\["[A-Z*]+", ".*"\]),$')

PREAMBLE = """package policy

http := input.attributes.request.http

path := split(http.path, "?")[0]

bearer := substring(http.headers.authorization, count("Bearer "), -1) if {
\tstartswith(http.headers.authorization, "Bearer ")
}

claims := payload if {
\t[_, payload, _] := io.jwt.decode(bearer)
}

authenticated if claims.sub

roles := object.get(claims, "roles", [])

requested(route) if {
\troute[0] in {http.method, "*"}
\tregex.match(route_patterns[route], path)
}"""

COVERAGE = """package policy_test

import data.policy

ruled := {route |
\tsome routes in policy.ruled_routes
\tsome route in routes
}

test_every_route_is_ruled if {
\tmissing := policy.routes - ruled
\tprint("routes with no rule in ruled_routes:", missing)
\tcount(missing) == 0
}

test_every_ruled_route_still_exists if {
\tstale := ruled - policy.routes
\tprint("ruled_routes lists routes the app no longer has:", stale)
\tcount(stale) == 0
}
"""


def route_key(route: Route) -> str:
    return json.dumps([route.method, route.path])


def pattern(template: str) -> str:
    trimmed = template.rstrip("/")
    pieces: list[str] = []
    position = 0
    for parameter in PATH_PARAMETER.finditer(trimmed):
        literal = trimmed[position : parameter.start()]
        catch_all = parameter.group().endswith(":path}")
        if (
            catch_all
            and parameter.end() == len(trimmed)
            and literal.endswith("/")
        ):
            pieces += [re.escape(literal[:-1]), "(?:/.*)?"]
        else:
            pieces += [re.escape(literal), ".*" if catch_all else "[^/]+"]
        position = parameter.end()
    pieces.append(re.escape(trimmed[position:]))
    regex = "".join(pieces)
    return f"^{regex}$" if regex.endswith((".*", ".*)?")) else f"^{regex}/?$"


def render(routes: list[Route]) -> str:
    keys = "".join(f"\t{route_key(r)},\n" for r in routes)
    patterns = "".join(
        f"\t{route_key(r)}: `{pattern(r.path)}`,\n" for r in routes
    )
    sections = [
        PREAMBLE,
        f"routes := {{\n{keys}}}" if routes else "routes := set()",
        f"route_patterns := {{\n{patterns}}}"
        if routes
        else "route_patterns := {}",
    ]
    return "\n\n".join(sections) + "\n"


def read_routes(rego: str) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for line in rego.split("\nroute_patterns := ", 1)[0].splitlines():
        match = ROUTE_ENTRY.match(line)
        if match is not None:
            method, path = json.loads(match.group(1))
            found.add((method, path))
    return found
