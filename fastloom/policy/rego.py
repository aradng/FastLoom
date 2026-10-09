import json
import re

from fastloom.policy.schemas import Route

ROUTES_FILE = "routes.rego"
COVERAGE_FILE = "routes_test.rego"

PATH_PARAMETER = re.compile(r"\{[^/}]+\}")
LISTED_ROUTE = re.compile(r'^\t(\["[A-Z*]+", ".*"\]): `', re.MULTILINE)

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
\tregex.match(route_patterns[route], path)
}

requested_group(group) if {
\tsome route in ruled_routes[group]
\trequested(route)
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
    return f"^{''.join(pieces)}/?$"


def render(routes: list[Route]) -> str:
    patterns = "".join(
        f"\t{json.dumps(r, ensure_ascii=False)}: `{pattern(r.path)}`,\n"
        for r in routes
    )
    listing = f"{{\n{patterns}}}" if routes else "{}"
    return f"{PREAMBLE}\n\nroute_patterns := {listing}\n"


def listed_routes(rego: str) -> set[Route]:
    return {Route(*json.loads(r)) for r in LISTED_ROUTE.findall(rego)}
