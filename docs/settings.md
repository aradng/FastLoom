# Settings & Configs

Core centralizes settings via `Configs` (an alias to `core_bluprint.tenant.settings.ConfigAlias`). It aggregates your project settings classes and exposes `Configs[SomeSettings].general` for access.

Common settings classes:

- `core_bluprint.settings.base.ProjectSettings` and `FastAPISettings`
- `core_bluprint.launcher.settings.LauncherSettings`
- `core_bluprint.db.settings.MongoSettings`
- `core_bluprint.signals.settings.RabbitmqSettings`
- `core_bluprint.observability.settings.ObservabilitySettings`

The launcher exposes your settings via endpoints. Toggle public visibility with `LauncherSettings.SETTINGS_PUBLIC`.
