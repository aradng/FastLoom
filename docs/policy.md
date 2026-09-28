# Policy (OPA route coverage)

A service that authorizes requests with Open Policy Agent keeps its rego in a `policy/` directory. `fastloom-policy` keeps that policy in step with the service's routes: a commit that adds a guarded route, removes one, or changes the role it needs fails until the rego says the same thing.

**Symbols at a glance**

- `fastloom-policy` — console script (`fastloom.policy.routes:main`).
- `.pre-commit-hooks.yaml` — `fastloom-policy-routes`, `opa-fmt`, `opa-check`, `opa-test`.

## What it generates

`fastloom-policy --package <rego package>`, run from the service root, builds the service's FastAPI app through the launcher factory — reading `tenants.yaml` exactly as `launch` does — without starting it, and reads its OpenAPI schema. It writes two files into `policy/` (`--policy-dir` to change it):

- `routes.json` — every operation as `{method, path, access}`. OPA loads it as `data.app_routes`.
- `fastloom_routes_test.rego` — coverage tests in the service's own package.

It exits `1` when either file changed, printing each route whose access changed, so a pre-commit run fails until the regenerated files are staged.

`access` comes from the operation's security requirement:

| OpenAPI `security` | `access` |
|---|---|
| none | `open` |
| OpenID Connect, no scopes | `user` |
| OpenID Connect with scopes | the scopes, e.g. `ADMIN` |

Role guards therefore have to be declared with `Security(..., scopes=[ROLE])` — see [auth.md](auth.md#declaring-a-role-guard). A role checked inside a plain `Depends` shows up as `user`.

Nothing connects to the services `tenants.yaml` points at; the app is built, never started. In CI, where `tenants.yaml` is not checked in, write it from the same variable the deploy job uses before running the command.

## What the service's rego provides

One rule, in the package passed as `--package`:

```rego
ruled_routes := {
	"user": {["GET", "/api/notify/notification"]},
	"ADMIN": {["GET", "/api/notify/admin/email/deliveries"]},
}
```

Keys are `access` values, members are `[method, path]` with the path exactly as the manifest spells it, path parameters included (`/api/x/{item_id}`). `open` routes need no entry. The generated tests fail when:

- a guarded route has no entry under its access,
- a role route is also under `user`,
- an entry names a route the app no longer has, or no longer guards that way.

## Pre-commit

```yaml
- repo: https://github.com/aradng/FastLoom
  rev: <fastloom version>
  hooks:
    - id: fastloom-policy-routes
      args: [--package, qubit.notify]
    - id: opa-fmt
    - id: opa-check
    - id: opa-test
```

`fastloom-policy-routes` is a `system` hook: it runs the `fastloom-policy` installed in the service's own environment, because it has to import the service. The `opa-*` hooks run the OPA image through Docker. In a CI job without Docker or the service's dependencies, skip them there and run `fastloom-policy` in the built service image and `opa test policy` in the OPA image instead.
