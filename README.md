# Fastloom – The Open Foundation for Building Event-Driven Services

Fastloom is a lightweight, batteries-included foundation for building modern backends. Define your settings, schemas, and endpoints; Fastloom wires up the rest: FastAPI, Mongo (Beanie), Rabbit (FastStream), metrics/traces/logs/errors, and more.

Think of it as the glue for your stack: web, messaging, caching, DB, observability, and integrations with best-in-class tools.

---

## Why Fastloom

- No boilerplate: minimal scaffolding/templating; most wiring is handled inside the library.
- Composable: opt into only what you need via extras (`fastapi`, `rabbit`, `kafka`, `mongo`, `redis`, `mcp`, `celery`, `openai`).
- Pydantic-first: type-safe models, validators, and clear input/output contracts.
- Multi-tenant by design: tenant context flows through DI and storage.
- AuthN/Z via DI: OIDC token introspection and pluggable PDP (ABAC/RBAC/ReBAC) hooks.
- Event-driven ready: publish/subscribe with routing keys and health.
- Observability-native: metrics, traces, logs from day one.
- Self-hostable: production parity with a cloud/aaS setup.

---

## Integrated Services (the platform)

Fastloom plugs into a family of self-hostable services:

- IAM → OIDC/SSO, authN/Z, RBAC/ABAC/ReBAC.
- Notify → realtime notifications, Pusher-compatible API.
- Pulse → user activity + event tracking with OpenTelemetry hooks.
- File → object storage on MinIO (S3-compatible).
- Finance, Subscription, SMS/Email, Meet, Persona → optional services you can wire in.

Each service is:
- self-hostable (Docker Compose or Helm),
- BaaS-available.

---

## Quick start

```bash
# Install fastloom with the extras you need
poetry add fastloom -E fastapi -E mongo -E rabbit
```

A minimal service is two files at the project root — `settings.py` and `app.py` — plus a `tenants.yaml` for defaults:

```python
# settings.py
from fastloom.db.settings import MongoSettings
from fastloom.launcher.settings import LauncherSettings
from fastloom.observability.settings import ObservabilitySettings
from fastloom.settings.general import BaseGeneralSettings
from fastloom.signals.rabbit.settings import RabbitmqSettings


class Settings(
    BaseGeneralSettings,
    LauncherSettings,
    MongoSettings,
    RabbitmqSettings,
    ObservabilitySettings,
): ...
```

```python
# app.py
from fastapi import APIRouter

from fastloom.launcher.schemas import App

from my_service import models, signals

router = APIRouter()


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"pong": "ok"}


app = App(
    routes=[(router, "", "Health")],
    models_module=models,
    signals_module=signals,
)
```

```yaml
# tenants.yaml
default:
    ENVIRONMENT: development
    PROJECT_NAME: my_service
    MONGO_URI: mongodb://localhost:27017
    MONGO_DATABASE: my_service
    RABBIT_URI: amqp://guest:guest@localhost:5672/
```

Run with the bundled CLI (registered as `launch` via `[project.scripts]`):

```bash
launch
```

See [docs/quickstart.md](docs/quickstart.md) for a fuller walkthrough.

---

## What you get out of the box

- App orchestrator (`fastloom.launcher`)
    - Discovers your routes, models, signals, and healthchecks from `app.py` / `settings.py`
    - Exposes settings and health endpoints (public toggle via `LauncherSettings.SETTINGS_PUBLIC`)
- FastAPI-native
    - Dependency-injected request/tenant context and guards
    - Clear routing, OpenAPI, and dependency injection patterns
- Auth & Access
    - DI-based guards with OIDC / OAuth2 token introspection
    - Optional IAM sidecar for introspection + ACL
- Multi-tenancy
    - Tenant-aware DI context across web, DB, and messaging
    - Per-tenant settings endpoint backed by DB + cache, with `tenants.yaml` defaults
- Database layer (MongoDB via Beanie)
    - Created/updated mixins, pagination utilities, typed helpers
    - Auto model discovery for DB init via `App.models_module`
- Signals / Messaging (Rabbit + Kafka via FastStream)
    - Rabbit: event-driven publish/subscribe with retries and DLX-based backoff
    - Kafka: subscriber/publisher wiring for consuming topics (e.g. Debezium CDC)
    - Subscriber wiring and healthchecks
    - Auto-streamed `BaseDocumentSignal` Beanie models
- Observability
    - OpenTelemetry distro + OTLP exporter, Logfire, Sentry (errors + profiling)
- I18N
    - Exception handler and template utils with Babel/Jinja2
- Healthchecks
    - Automatic app/DB/messaging/cache checks + system routes
- MCP
    - Optional FastMCP mount with bearer auth forwarding
- Pydantic-native schemas and validators
    - Schema In/Out validation for request/response contracts
    - Common types and validators (`fastloom.types`)

Dive deeper in the docs below.

---

## Documentation

- Quickstart → [docs/quickstart.md](docs/quickstart.md)
- Conventions → [docs/conventions.md](docs/conventions.md)
- Launcher & App model → [docs/launcher.md](docs/launcher.md)
- Settings & Configs → [docs/settings.md](docs/settings.md)
- Tenant → [docs/tenant.md](docs/tenant.md)
- Auth → [docs/auth.md](docs/auth.md)
- DB (Mongo/Beanie) → [docs/db.md](docs/db.md)
- Signals (Rabbit / Kafka) → [docs/signals.md](docs/signals.md)
- Cache (Redis) → [docs/cache.md](docs/cache.md)
- Healthchecks → [docs/healthcheck.md](docs/healthcheck.md)
- Observability → [docs/observability.md](docs/observability.md)
- File storage → [docs/file.md](docs/file.md)
- I18N → [docs/i18n.md](docs/i18n.md)
- MCP → [docs/mcp.md](docs/mcp.md)
- Testing → [docs/test.md](docs/test.md)
- Internal testing (fastloom's own suite) → [docs/internal-testing.md](docs/internal-testing.md)

---

## Claude Code integration

If you build services on top of fastloom and use Claude Code, you can install the `fastloom-sdk` plugin. It bundles:

- **Scaffolding skills** — `scaffold-fastloom-service`, `add-fastloom-route`, `add-rabbit-subscriber`.
- **Audit skill** — `audit-fastloom-settings` flags misuse in your `settings.py` / `tenants.yaml`.
- **Reference skill** — `fastloom-reference` ships the full `docs/` so Claude can ground its answers in the canonical documentation instead of guessing from training data.

```bash
/plugin marketplace add aradng/FastLoom
/plugin install fastloom-sdk@fastloom
```

Skills auto-activate from context (e.g. asking "how does fastloom auth work?" triggers `fastloom-reference`); explicit invocation is `/fastloom-sdk:<skill-name>`. The plugin is opt-in per user and doesn't ship via PyPI — it's distributed through the marketplace in this same repo.

---

## Roadmap

- More CLI scaffolds and blueprints.
- Automatic `pydantic-ai` agentic tool creation from APIs.
- Migrate PDP to [`OPAL`](https://github.com/permitio/opal) / [`opa`](https://github.com/open-policy-agent/opa) based.
