# Tenant

Multi-tenancy helpers and settings.

- `core_bluprint.tenant.settings.ConfigAlias` (aka `Configs`) centralizes access to your settings classes (project, FastAPI, Rabbit, Mongo, etc.).
- `core_bluprint.tenant.handler.init_settings_endpoints()` registers settings endpoints (public toggle via `LauncherSettings.SETTINGS_PUBLIC`).
- Tenancy-aware mixins are provided for models (e.g., `TenantMixin`).

See the `tenant` package for mixins, protocols, and utilities.
