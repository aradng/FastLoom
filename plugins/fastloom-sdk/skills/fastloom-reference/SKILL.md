---
name: fastloom-reference
description: Use as the canonical reference for any question about the fastloom Python library — how its launcher / settings / auth / DB / RabbitMQ / cache / MCP / i18n / file / healthcheck / observability / testing surfaces work. Triggers on phrases like "how does fastloom X", "fastloom auth/db/signals/mcp/...", "what does TC mean", "explain App / Configs / RabbitSubscriber / SelfSustaining", "fastloom convention for Y", or whenever the user asks about a fastloom symbol while editing a fastloom-based service. Also use when one of the other fastloom-sdk skills (scaffold-fastloom-service, add-fastloom-route, add-rabbit-subscriber, audit-fastloom-settings) needs to verify a detail before generating code.
---

# fastloom reference docs

This skill bundles the full fastloom documentation. When the user asks about a fastloom concept, **read the relevant file from `docs/` next to this `SKILL.md`** and ground your answer in it.

## Doc map — which file answers which question

| Topic | File |
|-------|------|
| Bootstrapping a new service, the `app.py` / `settings.py` contract, the `launch` CLI | `docs/quickstart.md` |
| `App` declarative model, startup order, lifespan composition, `LauncherSettings` | `docs/launcher.md` |
| Composing `Settings`, `Configs` / `TC.general`, `tenants.yaml` structure, env-var fallbacks | `docs/settings.md` |
| `TC[tenant]` / `TC.set`, cache→Mongo→YAML resolution, tenant dependency sources, `TenantMixin` | `docs/tenant.md` |
| `JWTAuth` / `UserClaims`, IAM topology (Casdoor/Keycloak + sidecar), `/introspect` and `/acl` | `docs/auth.md` |
| Beanie models, mixins (`CreatedUpdatedAtSchema`), `BasePaginationQuery`, `BaseDocumentSignal` | `docs/db.md` |
| `RabbitSubscriber`, publishers, subscribers, retry/backoff DLX topology, `init_streams` | `docs/signals.md` |
| `RedisHandler`, `BaseCache` / `BaseTenantSettingCache`, `HostTenantMapping`, `RedisGuardGate` | `docs/cache.md` |
| `init_healthcheck`, auto-registered checks, custom handlers | `docs/healthcheck.md` |
| `InitMonitoring`, `Instruments` enum, `infer_instruments`, OTel sampling, Sentry/Logfire | `docs/observability.md` |
| `CustomI18NException`, `i18n_exception_handler`, `get_template`, `lang_dict` | `docs/i18n.md` |
| `FileIn` / `FileObject` / `FileMessage` / `FileField`, outbox-matching pattern | `docs/file.md` |
| `MCPSettings`, FastMCP mount, bearer-forwarding auth | `docs/mcp.md` |
| `init_app` / `TC` / auth fixtures, `assert_deep_diff`, testcontainers `create_container` | `docs/test.md` |
| Cross-cutting conventions: typing rules, `SelfSustaining`, optional-import idiom, validators, naming, dedupe | `docs/conventions.md` |

## How to use this skill

When the user asks a question that touches one of the topics above:

1. **Read the matching file** with the `Read` tool. Paths are relative to this skill — e.g. `Read("docs/auth.md")`.
2. **Answer from the doc**, citing `docs/<file>.md` in your reply so the user can verify.
3. If the question spans multiple files (e.g. "how does auth flow into per-tenant settings?"), read each relevant file and synthesize.
4. If the user is editing a fastloom-based service and asks something underspecified ("how do I add a route?"), point them at the right doc *and* offer to invoke the dedicated scaffolding skill (e.g. `/fastloom-sdk:add-fastloom-route`).

## What's bundled

The `docs/` directory next to this SKILL.md is a symlink to the canonical `docs/` of the fastloom repository. At install time, Claude Code dereferences the symlink and copies the actual files into the plugin cache — the user gets a snapshot of the docs current to the installed plugin version.

To get newer docs, the user runs `/plugin update fastloom-sdk@fastloom` (when a newer version is published).

## Important: don't substitute training-data knowledge for what's in `docs/`

Fastloom moves. Field names, capability mixins, and conventions shift between versions. **If you're tempted to answer a fastloom question from memory, stop and read the doc first.** The doc is the source of truth — your training data is not.

## Cross-referencing the scaffolding skills

The other four fastloom-sdk skills (`scaffold-fastloom-service`, `add-fastloom-route`, `add-rabbit-subscriber`, `audit-fastloom-settings`) embed key rules inline, but when a user asks "why does this scaffold do X", come back here and read the matching doc.
