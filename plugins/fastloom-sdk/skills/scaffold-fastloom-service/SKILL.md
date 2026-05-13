---
name: scaffold-fastloom-service
description: Use when the user wants to set up a new fastloom-based service from scratch, bootstrap a fastloom project, or generate the initial app.py / settings.py / tenants.yaml scaffold for a service consuming the fastloom library. Triggers on phrases like "new fastloom service", "set up fastloom", "bootstrap fastloom", "scaffold a fastloom backend".
---

# Scaffold a new fastloom service

Generate the three files every fastloom service needs at its project root, plus the `pyproject.toml` extras hint.

## Confirm with the user first

Ask in one round:

1. **Service name** (used as the Python package and `PROJECT_NAME`).
2. **Capabilities needed** — multi-select from: `mongo`, `rabbit`, `kafka`, `redis`, `mcp`, `celery`, `httpx`, `openai`. `fastapi` is always included.
3. **IAM mode** — OIDC (`OIDC_URL`) or OAuth2 (`authorizationUrl` + `tokenUrl`) or none for local dev.

## Generate

Use the user's answers to produce these files. Write to `cwd` unless the user specifies a subdirectory.

### `pyproject.toml` (snippet to add or merge)

```toml
[project]
name = "<service-name>"
requires-python = ">=3.12,<3.14"
dependencies = [
    "fastloom[fastapi,<other-selected-extras>]>=0.4,<0.5",
]
```

### `settings.py`

Compose `Settings` from `BaseGeneralSettings + LauncherSettings` plus exactly the capability mixins the user picked. Always alias `Configs` as `TC`. Add a `TenantSettings(BaseModel)` placeholder with a `name: str` field. Reference: `docs/settings.md` in the fastloom repo.

### `tenants.yaml`

A `default:` block with the SCREAMING_SNAKE_CASE infrastructure fields (`MONGO_URI`, `RABBIT_URI`, `REDIS_URL` — only the ones matching selected extras), `ENVIRONMENT: development`, `PROJECT_NAME`, `APP_PORT: 8000`, `DEBUG: true`, observability toggles off. Add one example tenant block under `default:` with just `name:` and an optional `website_url:`. **Do not put `MONGO_DATABASE` or any infrastructure URI in the per-tenant overrides** — databases are shared across tenants; partition via the `tenant` field on documents.

### `app.py`

A minimal `App(...)` declaration: one demo router with a `/ping` route, `models_module=models` and `signals_module=signals` only if the user picked mongo / rabbit respectively. Include `cache_healthcheck=True` if redis is selected.

### Optional starter package

If the user said they want a fully working starter, also create:
- `<service-name>/__init__.py`
- `<service-name>/api/__init__.py` + a `ping.py` router with `GET /ping` returning `{"pong": "ok"}`
- `<service-name>/models/__init__.py` if mongo was picked
- `<service-name>/signals/__init__.py` if rabbit was picked

## Rules to follow

- **Pydantic-everywhere**, no `Any`, no untyped dicts (see fastloom's `.claude/rules/typing.md` if available).
- Settings field names are SCREAMING_SNAKE_CASE for capability fields; the per-tenant business-domain fields are snake_case.
- No `MONGO_DATABASE` in tenant overrides.
- Use `Str[T]` for URL/DSN fields in `Settings`.
- Use `Field(default_factory=...)` for runtime defaults.

## Done

Tell the user what to do next:

```sh
poetry install
launch
# Then visit http://localhost:8000/api/<service-name>/docs
```
