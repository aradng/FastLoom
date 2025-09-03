# Signals (Rabbit)

Core wires Rabbit subscribers and healthchecks when Rabbit settings are present.

- `core_bluprint.signals.depends.RabbitSubscriber` — FastAPI router for subscriptions and healthchecks.
- `core_bluprint.signals.healthcheck.get_healthcheck` — healthcheck factory.
- Configure via `core_bluprint.signals.settings.RabbitmqSettings` and include in your tenant settings.

At startup, the launcher initializes Rabbit first to ensure consumers are ready.
