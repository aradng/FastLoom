import json
import re
from collections.abc import Iterable

from fastloom.auth.roles import Clause, RoleLiteral
from fastloom.policy.source import Route

PACKAGE = "policy"
PATH_PARAMETER = re.compile(r"\{[^/}]+\}")
ACCESS_ENTRY = re.compile(r'^\t(\["[A-Z]+", ".*"\]): (".*"),?$')

PREAMBLE = f"""package {PACKAGE}

http := input.attributes.request.http

path := split(http.path, "?")[0]

bearer := substring(http.headers.authorization, count("Bearer "), -1) if {{
\tstartswith(http.headers.authorization, "Bearer ")
}}

claims := payload if {{
\t[_, payload, _] := io.jwt.decode(bearer)
}}

authenticated if claims.sub

roles := object.get(claims, "roles", [])

requested(route) if {{
\thttp.method == route[0]
\tregex.match(route_patterns[route], path)
}}
"""


def route_key(route: Route) -> str:
    return json.dumps([route.method, route.path])


def pattern(template: str) -> str:
    pieces: list[str] = []
    position = 0
    for parameter in PATH_PARAMETER.finditer(template):
        pieces.append(re.escape(template[position : parameter.start()]))
        pieces.append(
            ".+" if parameter.group().endswith(":path}") else "[^/]+"
        )
        position = parameter.end()
    pieces.append(re.escape(template[position:]))
    return f"^{''.join(pieces)}$"


def condition(literal: RoleLiteral) -> str:
    check = f"{json.dumps(literal.name)} in roles"
    return check if literal.present else f"not {check}"


def bodies(route: Route) -> list[list[str]]:
    if route.roles is None:
        return [["authenticated"]] if route.authenticated else [[]]
    return [
        ["authenticated", *map(condition, sorted_literals(clause))]
        for clause in route.roles.disjunction()
    ]


def sorted_literals(clause: Clause) -> list[RoleLiteral]:
    return sorted(clause, key=lambda lit: (lit.name, not lit.present))


def grant(key: str, body: list[str]) -> str:
    head = f"granted contains {key}"
    match body:
        case []:
            return head
        case [only]:
            return f"{head} if {only}"
    return f"{head} if {{\n" + "".join(f"\t{c}\n" for c in body) + "}"


def table(name: str, rows: Iterable[tuple[str, str]]) -> str:
    entries = "".join(f"\t{key}: {value},\n" for key, value in rows)
    return f"{name} := {{\n{entries}}}" if entries else f"{name} := {{}}"


def render(routes: list[Route]) -> str:
    sections = [
        PREAMBLE.rstrip("\n"),
        table(
            "route_access",
            ((route_key(r), json.dumps(r.access)) for r in routes),
        ),
        table(
            "route_patterns",
            ((route_key(r), f"`{pattern(r.path)}`") for r in routes),
        ),
        *(grant(route_key(r), body) for r in routes for body in bodies(r)),
    ]
    return "\n\n".join(sections) + "\n"


def read_access(rego: str) -> dict[tuple[str, str], str]:
    found: dict[tuple[str, str], str] = {}
    for line in rego.splitlines():
        match = ACCESS_ENTRY.match(line)
        if match is not None:
            method, route_path = json.loads(match.group(1))
            found[(method, route_path)] = json.loads(match.group(2))
    return found
