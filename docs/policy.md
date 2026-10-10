# Policy (OPA route coverage)

A service that authorizes requests with Open Policy Agent keeps its rego in a `policy/` directory. `fastloom-policy` generates one file there, `routes.rego`, with every route, its rule and the `allow` decision. The service fills in each route's rule in that file; the commit fails until every rule is filled and well formed, and `allow` denies anything a rule doesn't grant.

**Symbols at a glance**

- `fastloom-policy` — console script (`fastloom.policy.main:main`), in the `policy` extra (`fastloom[policy]`, which brings Starlette for its path patterns).
- `.pre-commit-hooks.yaml` — the `fastloom-policy` hook.

## What it writes

Run from a service root, `fastloom-policy` reads the service's source with the standard library's `ast` — it never imports it, so it needs none of the service's dependencies — and rewrites `policy/routes.rego` (`--policy-dir <dir>` to write elsewhere), in `package policy`:

- a fixed preamble:
  - `requested(route)` — the request's method is the route's (any, for `*`) and its path, query string dropped and percent-decoded, matches the route's pattern, also with its trailing slash added or removed: Starlette redirects `/x/` and `/x` to whichever the route declares, and that redirect has to get through. The same rule lets a bare mount root reach its mount.
  - `allow` — `false` by default. It is `true` when the request matches at least one route and **every** matched route's rule permits it. Requiring all of them is deliberate: when `/items/{id}` and `/items/special` both match, the policy can't know which one FastAPI dispatches to, so the stricter rule wins.
  - `http`, `path`, `bearer`, `claims`, `authenticated`, `roles`, `routes`, `matched`, `permits`, `slashed_path`, `guards` — the request, its token and the helpers `allow` uses. `bearer` is the token after an `Authorization` scheme of `Bearer` in any case, as FastAPI reads it. `authenticated` is a non-empty string `sub` on a token that hasn't expired. `io.jwt.decode` does not check the signature: verify the token at the edge (Envoy's `jwt_authn`) before `ext_authz`. `roles` is the token's `roles` claim, `[]` when it has none.
- one block per route, keyed by `[method, path]` with the path spelled as the route declares it:
  - `route_patterns[...]` — Starlette's own pattern for the path (`compile_path`): `{id}` is one segment, `{id:int}` digits, `{rest:path}` any suffix. A mount from `App(mounts=...)` is `["*", "<mount>/{path:path}"]`.
  - `route_rules[...]` — the route's rule. A new route gets `"todo"`; a rule already in the file is read back and written again as it is.

The preamble is regenerated on every run and a deleted route's block is dropped. Below the preamble the file holds only `prefix_rules`, `route_patterns` and `route_rules` statements: any other line there — a helper rule, a comment, the rest of a rule value cut by a blank line — fails the hook without writing, so nothing hand-written is lost; other rego goes in its own file. The names above are reserved in `package policy`; the service's rego must not define them, `default allow` included.

## What the service writes

The value of each `route_rules[...]` in `routes.rego`, replacing its `"todo"`:

```rego
route_patterns[["GET", "/api/notify/health"]] := `^/api/notify/health$`
route_rules[["GET", "/api/notify/health"]] := "public"

route_patterns[["GET", "/api/notify/notification"]] := `^/api/notify/notification$`
route_rules[["GET", "/api/notify/notification"]] := "authenticated"

route_patterns[["POST", "/api/notify/orders"]] := `^/api/notify/orders$`
route_rules[["POST", "/api/notify/orders"]] := [["owner:read", "admin:write"], ["admin"]]
```

- `"public"` — anyone, no token.
- `"authenticated"` — any valid token, whatever its roles.
- a list of role lists — a valid token holding every role of at least one inner list. The example reads (`owner:read` and `admin:write`) or `admin`. Inner rego sets (`{"admin"}`) work as well; role names are non-empty double-quoted strings.

The hook fails the commit, naming the route, when a route is new (its rule is written as `"todo"`), a rule is still `"todo"` or isn't one of the three forms above (a typo, an empty list, an empty role list), or a route was deleted (its block is dropped). It fails without writing anything when a rule's route can't be read or a route is listed twice. `allow` denies the same mistakes at runtime, so a rule that slips through still fails closed.

### Prefix rules

A service whose routers group by audience — everything under `/api/assistant/broker` is for brokers — can say so once, in `routes.rego`:

```rego
prefix_rules["/api/assistant/broker"] := [["broker"]]
```

Every request whose path is at or under that prefix must satisfy the prefix's rule **and** the rule of each route it matches, so `route_rules[["PUT", "/api/assistant/broker/{id}"]] := [["ADMIN"]]` then needs both `broker` and `ADMIN`. The prefix is checked against the request's decoded path, not the route templates, so a route like `/api/assistant/{name}` that also answers `/api/assistant/broker` can't slip past it. Prefixes stack: a request under `/api/x` and `/api/x/admin` needs both rules. A prefix matches whole path segments: `/api/assistant/brokerage` isn't under `/api/assistant/broker`. The value takes the same three forms as a route's rule (a `"public"` prefix adds nothing, being ANDed); the key is a literal path starting with `/`, without `{params}`. Each run keeps the prefix rules, sorted, right after the preamble, and fails the commit when one is malformed, listed twice, or covers no route — a mistyped prefix would otherwise guard nothing.

Rego the service writes for itself — an `allow if { ... }` for what roles don't cover, an internal key or a source address, and the helpers it needs — goes in its own files in `package policy`, which fastloom never touches. Rego ORs those rules with the generated one, so they can only grant more. Data-level checks — ownership of a row, anything that depends on the request body — stay in the service's code.

## What it reads

Starting from `app.py`'s `App(routes=[(router, prefix, ...), ...], mounts=[(path, app, ...), ...])` — a service without `routes` has none — it follows each router to the `APIRouter(...)` that defines it, resolving names through module and class bodies — imports, `as` aliases, re-exports and plain `name = other` assignments — and reads every call on that router in the modules `app.py` imports, directly or through other modules — a module nothing imports never runs, so a call there registers nothing:

- the route decorators `get`, `put`, `post`, `delete`, `patch`, `head`, `options`, `trace`, `websocket` (as `GET`) and `api_route(path, methods=[...])` — on a function inside an `if`, a `try` or a class body (not one nested in another function) or called as `router.get("/x")(endpoint)`, under an `as` alias or a plain `name = router` included;
- `include_router(child, prefix=...)`, `child` positional or `router=`, followed into the child router.

fastloom's own routes are generated too. The launcher's routes get blocks like any other: `GET /healthcheck`, the system endpoints `/tenant_schema`, `/tenant_settings` (`GET`, `POST`) and `/reload`, and the docs (`/docs`, `/docs/oauth2-redirect`, `/redoc`, `/openapi.json`), all under `API_PREFIX`. When the service's `Settings` in `settings.py` inherits `MCPSettings` — directly, through its own base classes, or through a module (`mcp.MCPSettings`); a base it can't follow fails the hook — the MCP endpoint is `["*", "<API_PREFIX>/mcp"]`; `KafkaSettings` or `RabbitmqSettings` add the broker's AsyncAPI page (`/kafkaapi` or `/rabbitapi`, its `.json` and `.yaml` and `POST .../try`). A capability switched off at runtime (`DOCS_ENABLED`, `MCP_ENABLED`) still gets its block; its rule then never matters.

Prefixes add up the way FastAPI adds them: the `App` entry, each `include_router`, then each `APIRouter(prefix=...)`. Every path starts with the service's `API_PREFIX` — `/api/<project name>`, the name read from `pyproject.toml` the way `PROJECT_NAME` defaults to it. [`reject_external`](launcher.md#reject_external) isn't read: a route behind it is still generated under `API_PREFIX`, where `reject_external` answers 404, and its bare path, which never passes the proxy, isn't listed.

Prefixes, paths and methods may be literals, module constants or enum members (`StrEnum` or `(str, Enum)`, `.value` included) the repo defines. A mount path already under `API_PREFIX` is kept as it is.

What it can't read without running the code fails the hook, naming what it couldn't read, instead of being guessed:

- f-strings, and names that aren't a string constant the repo defines;
- `add_api_route`, `add_api_websocket_route`, `add_route`, `add_websocket_route`, `route`, `websocket_route`, `mount` and `host` on a router;
- a router that isn't an `APIRouter(...)` the repo defines;
- arguments spread with `*` or `**` into `App(...)`, `APIRouter(...)` or a router call, a path with a converter Starlette doesn't know, and an `api_route` method that isn't an HTTP method;
- a non-literal `App(routes=...)`, `App(mounts=...)` or `api_route` `methods`, an `App` entry or mount that isn't a tuple, and an `app.py` without `App(...)`;
- a module-level name it reads that is bound more than once (`+=` included), or a list it reads that has a method called on it (`.append(...)`, `.extend(...)`);
- a followed module that doesn't parse, and a missing or nameless `pyproject.toml`.

## What it doesn't generate

- **Routes registered inside a function body.** A decorator on a function nested in another function, or a router call inside one, isn't read: the route is missing from `routes.rego`, so `allow` denies it.
- **CORS preflight.** An `OPTIONS` preflight is answered by the edge's CORS filter before `ext_authz` runs, so it never reaches the policy.

## What it assumes

- **The path is matched decoded.** `requested()` percent-decodes the path (keeping `+`) before matching, the way uvicorn decodes it for Starlette, so `/api/x/items/a%2Fsecret` is matched as `/api/x/items/a/secret` — the route FastAPI will run — and a malformed escape matches nothing. The proxy should still `normalize_path`, `merge_slashes` and reject escaped slashes (`path_with_escaped_slashes_action: REJECT_REQUEST`) so such requests never reach a service.
- **The edge verifies the token.** The policy decodes the JWT without checking its signature, `iss`, `aud` or `nbf`; only `sub` and `exp` are read.
- **The prefix is the pyproject name.** A `PROJECT_NAME` overridden in `tenants.yaml` changes `API_PREFIX` at runtime but not the generated paths, which then match nothing.

## OPA

The generated file starts with `import rego.v1`, so it loads on OPA 1.x and on 0.x releases that know `rego.v1` (0.59+, with `--v0-compatible` on 1.x as well). It expects the input of OPA's Envoy plugin over gRPC (`input.attributes.request.http`) and is meant to run behind the edge check that verifies the token: it reads the token's claims but never its signature.

## Pre-commit

```yaml
- repo: https://github.com/aradng/FastLoom
  rev: <fastloom version>
  hooks:
    - id: fastloom-policy
      # args: [--policy-dir, rules]
```

It runs on any change to a `.py` file, `pyproject.toml` or `routes.rego`, in pre-commit's own environment on Python 3.13 (`language_version`; prek downloads it when the image has an older Python, classic pre-commit needs a `python3.13` on `PATH`), so it reads 3.13 syntax whatever the service's own Python is — the same locally and in CI. It exits `1`, printing each route and what changed or what's wrong with it, when `routes.rego` was rewritten or a rule needs filling in or fixing, so the commit fails until every rule is right and the file is staged. Formatting and `opa check` are each service's own hooks; the generated file is already `opa fmt`-clean.
