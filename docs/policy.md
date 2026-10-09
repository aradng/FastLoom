# Policy (OPA route rules)

A service that authorizes requests with Open Policy Agent keeps its rego in a `policy/` directory. `fastloom-policy` generates the role part of that rego from the service's own route guards, so the rules OPA enforces are the ones the code declares.

**Symbols at a glance**

- `fastloom-policy` — console script (`fastloom.policy.main:main`).
- `.pre-commit-hooks.yaml` — the `fastloom-policy` hook.
- `TC.auth.require_roles` and the role expression language — see [auth.md](auth.md#requiring-roles).

## What it generates

Run from a service root, `fastloom-policy` reads the service's source — it never imports it, so it needs none of the service's dependencies — and writes `policy/routes.rego` (`--policy-dir` to change the directory), in `package policy`:

- `route_access` — every route and the access it needs: `open`, `user`, or its role expression.
- `granted` — the routes the request's caller may use. Each role expression is compiled to rule bodies: `|` becomes separate bodies, `&` conditions in one body, `!` a `not`. Every guarded body also requires `authenticated`.
- `requested(route)` — whether the request is for that route, matched on method and on a pattern built from the path template (`{id}` is one segment, `{rest:path}` any number).
- `http`, `path`, `bearer`, `claims`, `authenticated`, `roles` — the request and its token, decoded once. `roles` is `[]` for a token with no `roles` claim, the same default `UserClaims` has, so `!TRIAL` admits it.

The file is generated: don't edit it. The service's own rego in the same package holds `allow` and anything the code can't express:

```rego
package policy

default allow := false

allow if {
	some route in granted
	requested(route)
	not route in refused
}
```

## What it reads

Starting from `app.py`'s `App(routes=[(router, prefix, ...), ...])`, it follows each router into its module, resolving imports within the repo. A route's access combines:

- the router's `APIRouter(prefix=..., dependencies=[...])`,
- the decorator's `dependencies=[...]`,
- the endpoint's `Depends(...)` / `Security(...)` parameters,
- and, through them, the service's own dependency functions.

`TC.auth.get_claims` or `get_token` makes a route `user` (`TC.optional_auth` does not); `TC.auth.require_roles(expression)` adds the expression. Paths are prefixed with `/api/<project name>`, the name read from `pyproject.toml` as `PROJECT_NAME` defaults to.

What it can't read without running the code fails the hook instead of being guessed: `include_router`, `add_api_route`, a dependency returned by one of the service's own functions, a non-literal `dependencies` list, and role expressions built with f-strings.

## Pre-commit

```yaml
- repo: https://github.com/aradng/FastLoom
  rev: <fastloom version>
  hooks:
    - id: fastloom-policy
```

It exits `1` when `routes.rego` changed, printing each route whose access changed (`PUT /api/notify/notification/read: user -> ADMIN`), so the commit fails until the regenerated file is staged and reviewed against the service's own rules. It runs in pre-commit's own environment, so it works the same locally and in CI. Formatting, `opa check` and `opa test` are each service's own hooks.
