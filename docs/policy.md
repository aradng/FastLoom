# Policy (OPA route coverage)

A service that authorizes requests with Open Policy Agent keeps its rego in a `policy/` directory. `fastloom-policy` generates the list of the service's routes into that directory, together with tests that fail until the service's own rego gives every route a rule. Who may call a route is the service's to write; that every route has an answer is what the generated files enforce.

**Symbols at a glance**

- `fastloom-policy` — console script (`fastloom.policy.main:main`), in the `policy` extra (`fastloom[policy]`, which brings [libcst](https://libcst.readthedocs.io)).
- `.pre-commit-hooks.yaml` — the `fastloom-policy` hook.

## What it generates

Run from a service root, `fastloom-policy` reads the service's source with libcst — it never imports it, so it needs none of the service's dependencies — and writes two files into `policy/` (`--policy-dir <dir>` to write them elsewhere). Neither is edited by hand. Without libcst installed it exits `1` asking for `fastloom[policy]`.

`routes.rego`, in `package policy`:

- `route_patterns` — every route as `[method, path]`, the path spelled as the route declares it (`/api/notify/notification/{notification_id}`), mapped to the pattern its requests match. A mount from `App(mounts=...)` is `["*", "<mount>/{path:path}"]`: it answers any method on any sub-path.
- `routes` — the set of `route_patterns`' keys.
- `requested(route)` — the request's method is the route's (any, for `*`) and its path, query string dropped, matches the route's pattern: `{id}` — and `{id:int}`, `{id:uuid}`, any converter but `path` — is one segment, `{rest:path}` any suffix, including none. A trailing slash is optional either way, because FastAPI redirects `/x/` and `/x` to whichever the route declares and that redirect has to get through. Patterns overlap where routes do — `/items/{id}` and `/items/{rest:path}`, or an `{x:int}` and an `{x:uuid}` route on the same path — so `requested()` can be true for more than one route, and their groups' rules all apply.
- `requested_group(group)` — `requested()` for some route in `ruled_routes[group]`.
- `http`, `path`, `bearer`, `claims`, `authenticated`, `roles` — the request and its token, decoded once. `authenticated` is a non-empty string `sub` on a token that hasn't expired. `io.jwt.decode` does not check the signature: verify the token at the edge (Envoy's `jwt_authn`) before `ext_authz`. `roles` is `[]` for a token with no `roles` claim, the default `UserClaims` has.

These names — `http`, `path`, `bearer`, `claims`, `authenticated`, `roles`, `routes`, `route_patterns`, `requested`, `requested_group` — are reserved in `package policy`: the service's rego must not define them. It defines `ruled_routes` and `allow`.

`routes_test.rego`, in `package policy_test`: two tests over the service's `ruled_routes`. They fail when a route has no group, or when a group lists a route the app no longer has.

## What the service writes

`ruled_routes`, in `package policy`, puts every route in a group the service names, and `allow` decides each group:

```rego
package policy

default allow := false

ruled_routes := {
	"open": {["POST", "/api/notify/sendgrid/webhook"]},
	"signed_in": {["GET", "/api/notify/notification"]},
	"admin": {["GET", "/api/notify/admin/email/deliveries"]},
}

allow if requested_group("open")

allow if {
	requested_group("signed_in")
	authenticated
}

allow if {
	requested_group("admin")
	"ADMIN" in roles
}
```

Data-level checks — ownership, rows a caller may see, anything that depends on the request body — stay in the service's code.

## What it reads

Starting from `app.py`'s `App(routes=[(router, prefix, ...), ...], mounts=[(path, app, ...), ...])` — a service without `routes` has none — it follows each router to the `APIRouter(...)` that defines it, resolving names across the repo with libcst's `FullyQualifiedNameProvider`, and reads every call on that router anywhere in the repo:

- the route decorators `get`, `put`, `post`, `delete`, `patch`, `head`, `options`, `trace`, `websocket` (as `GET`) and `api_route(path, methods=[...])` — on a function at any depth (inside an `if`, a `try` or a class body) or called as `router.get("/x")(endpoint)`, in the router's own module or any module that imports it, under an `as` alias or a plain `name = router` included;
- `include_router(child, prefix=...)`, `child` positional or `router=`, followed into the child router.

Prefixes add up the way FastAPI adds them: the `App` entry, each `include_router`, then each `APIRouter(prefix=...)`. Paths start with the service's `API_PREFIX` — `/api/<project name>`, the name read from `pyproject.toml` the way `PROJECT_NAME` defaults to it — except under [`reject_external`](launcher.md#reject_external), which is only reachable on the bare path, so that is the path generated (`/internal/trade/chat/map`). `reject_external` counts wherever FastAPI applies it: a router's, an `include_router`'s or a route's `dependencies=[Depends(...)]`, or an endpoint parameter (`Annotated[None, Depends(reject_external)]`, `= Depends(reject_external)`), imported under any name.

Prefixes, paths and methods may be literals, module constants or enum members (`StrEnum` or `(str, Enum)`), the repo's or an installed package's. A mount path already under `API_PREFIX` is kept as it is.

What it can't read without running the code fails the hook, naming what it couldn't read, instead of being guessed:

- f-strings, and names that aren't a string constant the repo or an installed package defines;
- `add_api_route`, `add_api_websocket_route`, `add_route`, `add_websocket_route`, `route`, `websocket_route`, `mount` and `host` on a router;
- a router that isn't an `APIRouter(...)` the repo defines;
- a non-literal `App(routes=...)`, `App(mounts=...)`, `dependencies` or `api_route` `methods`, an `App` entry or mount that isn't a tuple, and an `app.py` without `App(...)`;
- a module-level name it reads that is bound more than once, or grown after it is bound (`+=`, `.append(...)`, `.extend(...)`);
- a route call whose endpoint it can't find, a followed module that doesn't parse, and a missing or nameless `pyproject.toml`.

## What it doesn't generate

- **Fastloom's own routes.** The launcher adds `/healthcheck`, the docs (`/docs`, `/redoc`, `/openapi.json`, unless `DOCS_ENABLED` is off), the system endpoints `/tenant_schema`, `/tenant_settings` and `/reload` (reachable only on the bare path, through `reject_external`, unless `SETTINGS_PUBLIC`), the MCP mount when `MCP_ENABLED`, and the broker routers. None of them are in `routes`: the proxy has to route them around the policy, or the service rules them by hand.
- **CORS preflight.** An `OPTIONS` preflight is answered by the edge's CORS filter before `ext_authz` runs, so it never reaches the policy.

## What it assumes

- **The proxy normalizes the path.** OPA matches the raw path while Starlette routes on the decoded one, so `/api/x/a%2Fb` or `/api/x//y` can mean different routes to each. Envoy has to normalize before `ext_authz`: `normalize_path`, `merge_slashes`, and `path_with_escaped_slashes_action: UNESCAPE_AND_FORWARD` (or `REJECT_REQUEST`).
- **The prefix is the pyproject name.** A `PROJECT_NAME` overridden in `tenants.yaml` changes `API_PREFIX` at runtime but not the generated paths, which then match nothing.

## Pre-commit

```yaml
- repo: https://github.com/aradng/FastLoom
  rev: <fastloom version>
  hooks:
    - id: fastloom-policy
      # args: [--policy-dir, rules]
```

It runs on any change to a `.py` file, `pyproject.toml` or the generated files, in pre-commit's own environment with libcst installed — the same locally and in CI. It exits `1` when either file changed, printing the routes added (`+ GET /api/notify/notification/count`) and removed, so the commit fails until the regenerated files are staged — and the service's `opa test` then fails until `ruled_routes` gives each added route a group. Formatting, `opa check` and `opa test` are each service's own hooks; the generated files are already `opa fmt`-clean.
