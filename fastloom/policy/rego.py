import json
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
TABLES = (RULES, PATTERNS, SCOPES)
OLD_STATEMENTS = tuple(f"{name}[" for name in TABLES)
TODO = '"todo"'
INDENTED = ("\t", " ", "]", "}")
DECODER = json.JSONDecoder()

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


def opens(line: str) -> bool:
    return line.startswith(OLD_STATEMENTS) or any(
        line in (f"{name} := {{", f"{name} := {{}}") for name in TABLES
    )


def statements(text: str) -> list[tuple[str, str, str]]:
    lines = text.split("\n")
    number = next(
        (i for i, line in enumerate(lines) if opens(line)), len(lines)
    )
    found: list[tuple[str, str, str]] = []
    while number < len(lines):
        line = lines[number]
        name = line.split(" ")[0].split("[")[0]
        if line.strip() == "" or line == f"{name} := {{}}":
            number += 1
        elif name in TABLES and line == f"{name} := {{":
            number, entries = table_entries(lines, number + 1)
            found += [(name, key, value) for key, value in entries]
        elif line.startswith(OLD_STATEMENTS):
            statement = [line]
            number += 1
            while number < len(lines) and lines[number].startswith(INDENTED):
                statement.append(lines[number])
                number += 1
            key, _, value = (
                "\n\t".join(statement)
                .removeprefix(f"{name}[")
                .partition("] := ")
            )
            found.append((name, key, value))
        else:
            raise PolicySourceError(
                f"{ROUTES_FILE}:{number + 1}: {line.strip()} is not part of "
                "a rule; keep other rego in its own file"
            )
    return found


def table_entries(
    lines: list[str], start: int
) -> tuple[int, list[tuple[str, str]]]:
    found: list[list[str]] = []
    current: list[str] = []
    level = 0
    for number, line in enumerate(lines[start:], start):
        if not current and line == "}":
            return number + 1, [entry("\n".join(e).strip()) for e in found]
        if not current and line.strip() == "":
            continue
        current.append(line)
        level += depth(line)
        if level <= 0:
            found.append(current)
            current, level = [], 0
    raise PolicySourceError(f"{ROUTES_FILE}: a table is never closed")


def depth(line: str) -> int:
    level = 0
    quote: str | None = None
    escaped = False
    for char in line:
        if escaped:
            escaped = False
        elif quote == '"' and char == "\\":
            escaped = True
        elif quote is not None:
            quote = None if char == quote else quote
        elif char in '"`':
            quote = char
        elif char in "[{(":
            level += 1
        elif char in "]})":
            level -= 1
    return level


def entry(text: str) -> tuple[str, str]:
    try:
        _, end = DECODER.raw_decode(text)
    except ValueError:
        end = 0
    key, colon, value = text[:end], *text[end:].lstrip().partition(":")[1:]
    if not colon:
        raise PolicySourceError(
            f"{ROUTES_FILE}: cannot read the key of {text.strip()}"
        )
    return key, value.strip().removesuffix(",").rstrip()


def read(text: str) -> tuple[list[RuleLine], list[ScopeLine]]:
    found = statements(text)
    return (
        [read_rule(key, value) for name, key, value in found if name == RULES],
        [
            read_scope(key, value)
            for name, key, value in found
            if name == SCOPES
        ],
    )


def read_rule(key: str, value: str) -> RuleLine:
    try:
        method, path, *_ = json.loads(key)
        return RuleLine(route=Route(method=method, path=path), value=value)
    except ValueError as e:
        raise PolicySourceError(
            f"{ROUTES_FILE}: cannot read the route in {RULES}[{key}]"
        ) from e


def read_scope(key: str, value: str) -> ScopeLine:
    try:
        return ScopeLine(prefix=PREFIX_ADAPTER.validate_json(key), value=value)
    except ValueError as e:
        raise PolicySourceError(
            f"{ROUTES_FILE}: cannot read the prefix in {SCOPES}[{key}]"
        ) from e
