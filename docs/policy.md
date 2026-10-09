# Policy (OPA route coverage)

A service that authorizes requests with Open Policy Agent keeps its rego in a `policy/` directory. `fastloom-policy` generates the list of the service's routes into that directory, together with tests that fail until the service's own rego gives every route a rule. Who may call a route is the service's to write; that every route has an answer is what the generated files enforce.

**Symbols at a glance**

- `fastloom-policy` — console script (`fastloom.policy.main:main`).
- `.pre-commit-hooks.yaml` — the `fastloom-policy` hook.

## What it generates

Run from a service root, `fastloom-policy` reads the service's source with [libcst](https://libcst.readthedocs.io) — it never imports it, so it needs none of the service's dependencies — and writes two files into `policy/` (`--policy-dir` to change it). Neither is edited by hand.

`routes.rego`, in `package policy`:

- `routes` — every route as `[method, path]`, the path spelled as the route declares it (`/api/notify/notification/{notification_id}`). A mount from `App(mounts=...)` is `["*", "<mount>/{path:path}"]`: it answers any method on any sub-path.
- `route_patterns` and `requested(route)` — whether the request is for a route: the method (any, for `*`), and the path against an escaped pattern where `{id}` is one segment and `{rest:path}` any number, including none. A trailing slash is optional either way, because FastAPI redirects `/x/` and `/x` to whichever the route declares and that redirect has to get through.
- `http`, `path`, `claims`, `authenticated`, `roles` — the request and its token, decoded once. `roles` is `[]` for a token with no `roles` claim, the default `UserClaims` has.

`routes_test.rego`, in `package policy_test`: two tests over the service's `ruled_routes`. They fail when a route has no group, or when a group lists a route the app no longer has.

## What the service writes

`ruled_routes`, in `package policy`, puts every route in a group the service names, and the service's rules decide each group:

```rego
package policy

default allow := false

ruled_routes := {
	"open": {["POST", "/api/notify/sendgrid/webhook"]},
	"signed_in": {["GET", "/api/notify/notification"]},
	"admin": {["GET", "/api/notify/admin/email/deliveries"]},
}

allow if {
	some route in ruled_routes.signed_in
	requested(route)
	authenticated
}

allow if {
	some route in ruled_routes.admin
	requested(route)
	"ADMIN" in roles
}
```

Data-level checks — ownership, rows a caller may see, anything that depends on the request body — stay in the service's code.

## What it reads

Starting from `app.py`'s `App(routes=[(router, prefix, ...), ...], mounts=[...])` — a service without `routes` has none — it follows each router into its module, resolving names across the repo with libcst's `FullyQualifiedNameProvider`, and each `router.include_router(child, prefix=...)` into the child router. Prefixes add up the way FastAPI adds them: the `App` entry, `include_router`, then `APIRouter(prefix=...)`. Paths start with `/api/<project name>`, the name read from `pyproject.toml` as `PROJECT_NAME` defaults to, except under a router or route depending on [`reject_external`](launcher.md#reject_external): those are only reachable on the bare path, so that is the path generated (`/internal/trade/chat/map`).

Prefixes, paths and methods may be literals or module constants. What it can't read without running the code fails the hook instead of being guessed: f-strings, `add_api_route` and the other imperative registrations, a router that isn't an `APIRouter(...)` the repo defines, and a non-literal `dependencies` list.

## Pre-commit

```yaml
- repo: https://github.com/aradng/FastLoom
  rev: <fastloom version>
  hooks:
    - id: fastloom-policy
```

It exits `1` when either file changed, printing the routes added (`+ GET /api/notify/notification/count`) and removed, so the commit fails until the regenerated files are staged — and the service's `opa test` then fails until `ruled_routes` gives each added route a group. It runs in pre-commit's own environment, the same locally and in CI. Formatting, `opa check` and `opa test` are each service's own hooks.
