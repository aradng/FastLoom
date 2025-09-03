# Observability

Production-grade observability with minimal setup.

- OpenTelemetry distro and OTLP exporter support
- Logfire and Sentry integrations
- Auto-instrumentation for FastAPI, HTTPX, Redis, Mongo, Rabbit (optional)

Use `core_bluprint.monitoring.InitMonitoring` and `Instruments` in the launcher. Configuration lives under `core_bluprint.observability.settings`.
