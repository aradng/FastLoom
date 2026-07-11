# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Fastloom is a Python library (`fastloom`, published to PyPI; CLI entrypoint `launch`) that provides a batteries-included foundation for building event-driven, multi-tenant FastAPI services. It wires together FastAPI, MongoDB (Beanie), RabbitMQ/Kafka/Redis (via FastStream), OpenTelemetry/Logfire/Sentry, OIDC auth, i18n, and an optional FastMCP mount. Services consuming this library define an `app.py` and `settings.py` at their project root, and the library's launcher discovers them dynamically.

Note: the README and `docs/` still refer to the package as `core_bluprint` — that's stale. The actual package is `fastloom`.

## Commands

Poetry-managed, Python 3.12+ (CI builds with 3.13). All dev tooling runs through pre-commit.

```bash
# Install with all optional groups you need (mongo, rabbit, kafka, redis, fastapi, mcp, openai, celery, httpx, requests)
poetry install -E fastapi -E mongo -E rabbit --with dev,test

# Lint + format + type-check + poetry-check + poetry-lock (full pre-commit suite)
poetry run pre-commit run --all-files --show-diff-on-failure

# Individual tools
poetry run ruff check .
poetry run ruff format .
poetry run mypy fastloom

# Tests (pytest with asyncio + xdist + testcontainers)
poetry run pytest                       # full suite
poetry run pytest path/to/test_file.py::test_name  # single test
poetry run pytest -n auto               # parallel
poetry run pytest --cov=fastloom        # with coverage

# Build / publish (CI does this on main)
poetry build
poetry publish
```

CI (`.github/workflows/ci.yaml`) runs pre-commit on every PR and publishes to PyPI on push to `main`. GitLab CI (`.gitlab-ci.yml`) publishes to an internal Nexus registry instead — both pipelines coexist.

## Architecture

### Launcher / App lifecycle (`fastloom/launcher/`)

A consuming service has two well-known top-level modules that the launcher imports dynamically via `importlib`:

- `settings.py` must expose a `Settings` class (and optionally `TenantSettings`). These are pydantic models that mix in the capability settings the service needs (e.g. `MongoSettings`, `RabbitmqSettings`, `RedisSettings`, `IAMSettings`, `MCPSettings`, `ObservabilitySettings`, `FastAPISettings`, `LauncherSettings`).
- `app.py` must expose an `app: fastloom.launcher.schemas.App` instance declaring `routes`, `models_module` (auto-discovered Beanie documents), `signals_module`, `healthchecks`, `mounts`, `lifespan_fn`, `exception_handlers`, and `additional_instruments`.

`fastloom.launcher.main:app` is the FastAPI factory (`launch` runs it via `uvicorn ... --factory`). Startup order, enforced in `main.py`, is **load-bearing**: Rabbit subscriber initializes before `InitMonitoring` so that aio-pika instrumentation can attach; FastAPI instrumentation runs **after** all middlewares/routes are loaded; MCP and the broker each contribute their own lifespan that's combined via `combine_lifespans()` (LIFO entry/exit, merged dict results).

### Configs / multi-tenancy (`fastloom/tenant/settings.py`)

`Configs` (alias: `fastloom.tenant.settings.ConfigAlias`) is a generic singleton (built on `SelfSustaining`, a metaclass-driven class-level singleton in `fastloom/meta.py`) that holds the merged settings. Access pattern is always **`Configs[SomeCapabilitySettings].general.FIELD`** — `Configs[X]` returns the singleton's view filtered to fields defined on capability class `X`. Tenant-specific overrides are loaded from `tenants.yaml` and/or Mongo (`BaseTenantSettingsDocument`) and/or a Redis-backed cache (`BaseTenantSettingCache`); resolution order is cache → document → in-memory YAML map. `Configs.get(tenant)` returns the resolved `TenantSettings`; `Configs.set(tenant, value)` strips defaults before persisting.

When extending behavior that touches settings, prefer adding a new capability mixin class (subclass of `BaseModel` / `MonitoringSettings`) and gating logic with `isinstance(Configs[Capability].general, Capability)` rather than feature flags.

### Optional-dependency import pattern

The library has many optional extras (`mongo`, `rabbit`, `kafka`, `redis`, `mcp`, `openai`, …). Modules that depend on an extra use this exact pattern so type-checkers see the real symbol while runtime falls back gracefully:

```python
if TYPE_CHECKING:
    from beanie import Document
else:
    try:
        from beanie import Document
    except ImportError:
        from pydantic import BaseModel as Document
```

When adding new optional integrations, follow the same shape and gate runtime instantiation behind a precomputed `fastloom.extras.X_INSTALLED` constant (backed by `fastloom.launcher.utils.is_installed("module_name")`, computed once at import time — add a new constant there rather than calling `is_installed` ad hoc) or `isinstance(Configs[X].general, X)`.

### Signals / messaging (`fastloom/signals/`)

`RabbitSubscriber` is another `SelfSustaining` singleton. It owns the FastStream `RabbitRouter`, an exception middleware, and a retry/backoff topology built on a side channel (`_topology_connection` / `_topology_channel` with `_topology_lock`). Subscribers are discovered from `App.signals_module` at startup, **after** the subscriber singleton is constructed. Models that inherit `BaseDocumentSignal` (Beanie + signal mixin) are auto-streamed via `init_streams()`.

### Observability (`fastloom/monitoring.py`)

`InitMonitoring` is a context manager invoked once during app construction. It configures Logfire, Sentry, and OTel from `ObservabilitySettings`, and `infer_instruments()` automatically enables Redis/Rabbit/Mongo/Pydantic-AI instrumentation based on which capability settings classes the service inherits. Pass `otel_sampling: logfire.SamplingOptions` on `App` to override sampling. `monitor.instrument(app, …)` is called **last** in the factory because FastAPI instrumentation must run after middlewares.

### Database (`fastloom/db/`)

Beanie ODM. Models live in a module registered via `App.models_module`; `get_models()` auto-discovers `Document` / `View` / `UnionDoc` subclasses. Mixins to reuse: `CreatedAtSchema`, `CreatedUpdatedAtSchema` (uses `@before_event` — only valid on `Document`, **note that `update_many` bypasses `updated_at`**), `BasePaginationQuery`, `PaginatedResponse[T]`.

### Auth (`fastloom/auth/`)

`JWTAuth` (required) and `OptionalJWTAuth` use FastAPI security schemes (OIDC or OAuth2). Token validation can hit an IAM sidecar for introspection (`/introspect`) and ACL (`/acl`); both are opt-in via `IAMSettings.INTROSPECT` and `.ACL`. Claims are normalized into `UserClaims` and stashed in a contextvar (`fastloom.auth.Claims`) — read claims via `Claims.get()` rather than re-parsing the token.

### MCP (`fastloom/mcp/`)

When `MCPSettings.MCP_ENABLED` is set, a FastMCP ASGI app is mounted at `API_PREFIX` and its lifespan is composed into the FastAPI lifespan. Bearer auth is forwarded via a connector header proxy (see commit `358cd57`).

## Conventions

- **Ruff:** `line-length = 79`, double-quoted strings, magic trailing commas preserved. Selected rule families: `E,W,F,C90,UP,B,SIM,INT,I,FAST`. `F401` is never auto-fixed (unused imports are flagged but not removed). `__init__.py` ignores `F` and `E402`; `tests/`, `docs/`, `tools/` ignore `E402`.
- **mypy:** strict pydantic + returns plugins; `init_forbid_extra = true`, `init_typed = true`, `warn_required_dynamic_aliases = true`.
- **Pydantic v2 only.** Use `model_validate`, `model_dump`, `Field(default_factory=…)`. Many helpers (`create_optional_model`, `optional_fieldinfo`) live in `fastloom/meta.py`.
- **Settings classes use SCREAMING_SNAKE_CASE field names** (`MONGO_URI`, `RABBIT_URI`, `API_PREFIX`), since they double as env-var names — see `fastloom/settings/utils.py` (`pydantic_env_or_default`, `get_env_or_err`).
- **Generic singletons:** anything class-level-singleton uses `SelfSustaining` from `fastloom/meta.py`. Access via `Cls.self` or `Cls.<attr>` directly (the metaclass forwards).
- Datetimes: use `fastloom.date.utcnow` (not naive `datetime.utcnow()`).
- The `sandbox/` directory holds local experiments and is **not** part of the published package.

## Testing

- `pytest-asyncio` + `pytest-xdist` + `testcontainers` are configured. `fastloom/test/` contains reusable fixtures (`app.py`, `auth.py`, `docker.py`, `settings.py`) and a `create_container` helper that authenticates against a private Docker registry via `REGISTRY_ADDRESS` / `REGISTRY_USERNAME` / `REGISTRY_PASSWORD` env vars.
- `fastloom.test.utils` provides `assert_deep_diff`, `status_check`, `assert_success`, `random_mobile_number`, `expect_calling`, `to_dict`, `generate_token`, `token_to_header`, `ignore_keys` — prefer these over hand-rolled assertions for response comparison (`assert_deep_diff` handles `ObjectId`/`PydanticObjectId`/`str` equivalence and treats `...` as a wildcard).
