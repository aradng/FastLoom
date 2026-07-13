---
name: audit-fastloom-settings
description: Use when the user wants to review, audit, lint, or sanity-check the settings.py and tenants.yaml of a fastloom-based service. Flags misuse like infrastructure fields in per-tenant overrides, missing default block, untyped fields, defaults re-stated in YAML, or settings access patterns that bypass the TC singleton. Triggers on "audit settings", "review my settings", "check tenants.yaml", "what's wrong with my fastloom config".
---

# Audit a fastloom service's settings

Walk through `settings.py` and `tenants.yaml` and report violations of fastloom conventions. **This skill does not auto-fix** — it produces a findings report; ask the user before changing files.

## Files to read

1. `settings.py` — must export `Settings`, optionally `TenantSettings`, and ideally `TC: type[Configs[Settings, TenantSettings]] = Configs`.
2. `tenants.yaml` — must have a `default:` top-level key.
3. `tenants.example.yaml` if present.
4. `app.py` — confirm `App(...)` references match what `Settings` enables.
5. Optional: grep the project for `Configs[`, `TC[`, `dict.get`, `getattr(` to spot anti-patterns.

## Checks to run

### A. `settings.py` structure

- [ ] `Settings` exists and is a single `class Settings(...)` inheriting capability mixins from `fastloom.*.settings`.
- [ ] Inherits `BaseGeneralSettings` (or at minimum `FastAPISettings + MonitoringSettings`).
- [ ] Inherits `LauncherSettings` for `APP_PORT` / `DEBUG` / `WORKERS`.
- [ ] Capability mixin coverage matches the actual `pyproject.toml` `fastloom` extras line.
- [ ] All capability fields use SCREAMING_SNAKE_CASE. ❗ Flag any lowercase or PascalCase capability field.
- [ ] URL/DSN fields use `Str[T]` (e.g. `Str[HttpUrl]`, `Str[AmqpDsn]`, `Str[RedisDsn]`), not `HttpUrl` directly. Reason: downstream callers (uvicorn, mongo client) need a plain `str`.
- [ ] `TenantSettings` (if present) contains only tenant-domain fields (snake_case business data). ❗ Flag if it contains infrastructure URIs, credentials, or env-var-style fields.
- [ ] `TC` alias is defined (or `Configs` is used directly). ❗ Flag if neither is exported.
- [ ] If `TC = Configs(service_cls=..., tenant_cls=...)` (eager binding, not `TC: type[Configs[...]] = Configs`), check the project's `conftest.py` for a module-scope (not fixture) call to `patch_tenant_loader_at_import` before any other local import. ❗ Flag eager binding with no such call, or one wrapped in a `@pytest.fixture` — fixtures run after collection, too late to protect an eager binding. See `docs/conventions.md#eager-vs-deferred-tcgeneral-reads`.
- [ ] No `__init__` defaults — defaults belong on `Field(default=...)` / `Field(default_factory=...)`.
- [ ] No `model_validator` that just fills defaults (defaults belong on the field).

### B. `tenants.yaml` structure

- [ ] `default:` block is present at the top.
- [ ] `default:` contains all infrastructure URIs (`MONGO_URI`, `RABBIT_URI`, `REDIS_URL`) — these are **shared across tenants**.
- [ ] `default:` contains `ENVIRONMENT`, `PROJECT_NAME`, `APP_PORT`, `DEBUG`, and observability toggles.
- [ ] **No tenant override contains `MONGO_URI`, `MONGO_DATABASE`, `RABBIT_URI`, `REDIS_URL`, or any other infrastructure field.** ❗ Flag each occurrence — databases are shared; partition via the `tenant` field on documents.
- [ ] Per-tenant blocks only contain snake_case business-domain fields (matching `TenantSettings`).
- [ ] No field in `tenants.yaml` re-states a `Field(default=...)` value from `settings.py`. ❗ Flag — defaults live in one place.
- [ ] No secrets (API keys, passwords, JWT signing keys) in the YAML if it's committed. Suggest moving to env vars via `pydantic_env_or_default`.

### C. `tenants.example.yaml` (if present)

- [ ] Mirrors `tenants.yaml` structure with placeholder values.
- [ ] **Every field in `Settings` / `TenantSettings` that doesn't have a default is represented** so a fresh contributor sees what they need to fill in.
- [ ] Fields with defaults are **omitted** (the YAML is a template for non-default values).

### D. Access patterns (project-wide grep)

- [ ] `TC.general.X` is the standard read pattern. ⚠ Note (don't error) any `Configs[X].general` — works but verbose; recommend `TC.general` for new code.
- [ ] `await TC.set(tenant, value)` is the standard write — never `TC[tenant] = value`.
- [ ] No re-instantiation of `Settings()` outside the launcher. ❗ Flag.
- [ ] No `dict.get` on a typed dict or `getattr(obj, name)` on a typed object — the schema is wrong if you need these.

## Report shape

Group findings by severity. Each finding cites the file + line.

```
## settings.py

- ❌ <file>:<line> Field `mongo_uri` is lowercase. Capability fields must be SCREAMING_SNAKE_CASE.
- ⚠  <file>:<line> URL field `MONGO_URI: str` should use `Str[HttpUrl]` so pydantic validates the input.
- ℹ  Consider exporting `TC = Configs` for ergonomics.

## tenants.yaml

- ❌ tenant `acme` overrides `MONGO_DATABASE`. Databases are shared across tenants — remove this and partition via the `tenant` field on documents.
- ⚠  `default:` has `LOG_LEVEL: info`, but `LoggingSettings.LOG_LEVEL` already defaults to `info`. Drop the YAML line.

## Access patterns

- ⚠  <file>:<line> Uses `Configs[FastAPISettings].general.API_PREFIX`. Prefer `TC.general.API_PREFIX` in user code.

## Summary

- 1 must-fix, 2 nice-to-fix, 1 recommendation.
```

## After the report

Ask the user: "Want me to apply any of these fixes?" Don't auto-edit.
