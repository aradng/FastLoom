# Fastloom – The Open Foundation for Building Event-Driven Services

Fastloom is a lightweight, batteries-included foundation for building modern backends. Define your settings, schemas, and endpoints; Fastloom wires up the rest: FastAPI, Mongo (Beanie), Rabbit (FastStream), metrics/traces/logs/errors, and more.

Think of it as the glue for your stack: web, messaging, caching, DB, observability, and integrations with best-in-class tools.

---

## Why FastLoom

- No boilerplate: minimal scaffolding/templating; most wiring is handled inside Core.
- Composable: opt into only what you need (`FastAPI`, `Rabbit`, `MongoDB`, `Redis`, `OpenAI`).
- Pydantic-first: type-safe models, validators, and clear input/output contracts.
- Multi-tenant by design: tenant context flows through DI and storage.
- AuthN/Z via DI: OIDC token introspection and pluggable PDP (ABAC/RBAC/ReBAC) hooks.
- Event-driven ready: publish/subscribe with routing keys and health.
- Observability-native: metrics, traces, logs from day one.
- Self-hostable: production parity with a cloud/aaS setup.

---

## Integrated Services (the platform)

Core plugs into a family of self-hostable services:

- IAM → OIDC/SSO, authN/Z, RBAC/ABAC/ReBAC.
- Notify → realtime notifications, Pusher-compatible API.
- Pulse → user activity + event tracking with OpenTelemetry hooks.
- File → object storage on MinIO (S3-compatible).
- Finance, Subscription, SMS/Email, Meet, Persona → optional services you can wire in.

Each service is:
- self-hostable (Docker Compose or Helm),
- BaaS-available,

---

## Quick start

```bash
# Install core
poetry add core-bluprint -E FastAPI

# Scaffold a new service
launch init myservice --stack fastapi

# Run it
cd myservice
launch dev
```

See pyproject extras for the full list.

---

## What you get out of the box

- App orchestrator (`core_bluprint.launcher`)
  - Loads your routes, models, signals, and healthchecks
  - Exposes settings and health endpoints (public toggle)
- FastAPI-native
  - Dependency-injected request/tenant context and guards
  - Clear routing, OpenAPI, and dependency injection patterns
- Auth & Access
  - DI-based guards with OIDC token introspection
  - Pluggable PDP for ABAC/RBAC/ReBAC decisions
- Multi-tenancy
  - Tenant-aware DI context across web, DB, and messaging
  - Automatic per-tenant settings endpoint backed by DB + cache
- Database layer (MongoDB via Beanie)
  - Created/updated mixins, pagination utilities, typed helpers
  - Helper classes/methods for common patterns (queries, projections, pagination)
  - Auto model discovery for DB init
- Signals / Messaging (Rabbit via FastStream)
  - Event-driven publish/subscribe integration with DI and retries
  - Subscriber wiring and healthchecks
- Observability
  - OpenTelemetry distro + OTLP exporter, Logfire, Sentry (error/bug tracking)
- I18N
  - Exception handler and template utils with Babel/Jinja2
- Healthchecks
  - Automatic app/DB/messaging checks + system routes
- Pydantic-native schemas and validators
  - SchemaIn/Out validation for request/response contracts
  - Common types and validators (`core_bluprint.types`)

Dive deeper in the docs below.

---

## Documentation

- Auth → docs/auth.md
- Tenant → docs/tenant.md
- DB (Mongo/Beanie) → docs/db.md
- Signals (Rabbit) → docs/signals.md
- Observability → docs/observability.md
- File storage → docs/file.md
- I18N → docs/i18n.md
- Settings & Configs → docs/settings.md
- Launcher & App model → docs/launcher.md

---

## Roadmap

- More CLI scaffolds and blueprints.
- Automatic `pydantic ai` agentic tool creation from apis
- Migrate PDP to [`OPAL`](https://github.com/permitio/opal) [opa](https://github.com/open-policy-agent/opa) based
