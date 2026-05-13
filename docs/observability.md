# Observability

Logfire + OpenTelemetry + Sentry, configured from a single settings mixin. Instrumentation is auto-enabled for the capabilities your service actually uses; you can also add custom instruments per request.

**Symbols at a glance**

- `fastloom.monitoring.InitMonitoring` — context manager that configures everything.
- `fastloom.monitoring.Instruments` — enum of supported integrations (`REDIS`, `CELERY`, `RABBIT`, `HTTPX`, `REQUESTS`, `METRICS`, `MONGODB`, `PYDANTIC`, `PYDANTIC_AI`, `OPENAI`).
- `fastloom.monitoring.infer_instruments` — auto-picks instruments based on `Settings` mixins.
- `fastloom.monitoring.SuppressOtelForPathsMiddleware` — disables instrumentation on regex-matched paths.
- `fastloom.monitoring.instrument_*` — per-integration helpers (`instrument_fastapi`, `instrument_httpx`, etc.).
- `fastloom.observability.settings.ObservabilitySettings` — knobs documented below.
- `fastloom.observability.settings.OtelConfig` — env-backed OTel exporter config.

## Settings

```python
class ObservabilitySettings(MonitoringSettings, OtelConfig):
    SENTRY_ENABLED: int = 0
    OTEL_ENABLED: int = 0
    SENTRY_DSN: AnyHttpUrl | None = None
    METRICS: bool = False
```

`OtelConfig` exposes the standard OTel exporter env vars (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_PROTOCOL`, `OTEL_LOGS_EXPORTER`, etc.) and copies them into `os.environ` at startup. Every field is `EnvBackend[T]` — it reads from the env var of the same name if set, otherwise from the literal default.

`FastAPISettings.EXCLUDED_ENDPOINTS` is a tuple of regex patterns (default: `r"/api/\w+/healthcheck"`, `r"/healthcheck"`) that should not be traced. The launcher installs `SuppressOtelForPathsMiddleware` for those patterns.

## What gets enabled

`InitMonitoring` does this on `__enter__`:

1. If `SENTRY_ENABLED=1`, calls `sentry_sdk.init(...)` with traces + profiling enabled (`profile_lifecycle="trace"`, `traces_sample_rate=1.0`). PydanticAI and FastMCP integrations are added automatically when those modules are importable.
2. If `OTEL_ENABLED=1`, calls `logfire.configure(...)` with `send_to_logfire="if-token-present"` (no Logfire token in env → no upload), plus the OTLP metrics reader when `OTEL_EXPORTER_OTLP_ENDPOINT` is set.
3. Calls every instrument in `only=` (your `additional_instruments` + auto-inferred ones).
4. On `monitor.instrument(app, ...)` (called last by the launcher), runs `instrument_fastapi(app, ...)` so middlewares and routes are visible.

`infer_instruments(Settings)` enables:

| Triggered by | Instrument |
|--------------|------------|
| `httpx` importable | `HTTPX` |
| `RedisSettings` in mixin chain | `REDIS` |
| `RabbitmqSettings` in mixin chain | `RABBIT` |
| `MongoSettings` in mixin chain | `MONGODB` |
| `ObservabilitySettings.METRICS=True` | `METRICS` (system metrics: cpu, mem, …) |
| `pydantic_ai` importable | `PYDANTIC_AI` |

## Custom instruments

Pass extra callables via `App.additional_instruments`:

```python
from fastloom.launcher.schemas import App
from logfire import instrument_asyncpg, instrument_pydantic_ai

app = App(
    additional_instruments=[instrument_asyncpg, instrument_pydantic_ai],
    ...
)
```

Anything callable works. If you need to pass arguments, wrap in a partial.

## Sampling

Override OTel sampling on `App.otel_sampling`:

```python
import logfire
from opentelemetry.sdk.trace.sampling import ParentBased

from fastloom.launcher.schemas import App

app = App(
    otel_sampling=logfire.SamplingOptions(head=ParentBased(MyCustomSampler())),
    ...
)
```

`logfire.SamplingOptions` is passed straight into `logfire.configure(sampling=...)`. Use a head-based parent sampler when you want to make sampling decisions before a span is created.

## FastAPI hooks

`instrument_fastapi` attaches two hooks:

- `_server_request_hook` — if the request carries a bearer token, parses it and attaches `username`, `user_id`, `tenant` attributes to the active span.
- A custom `StarletteHTTPException` handler records the status text on the span and returns a JSON `{"detail": ...}` body.

It also passes `excluded_urls` from `FastAPISettings.EXCLUDED_ENDPOINTS`.

## Suppressing paths

For paths that should not be instrumented at all (e.g. high-frequency polling endpoints), add patterns to `FastAPISettings.EXCLUDED_ENDPOINTS`. The middleware sets `_SUPPRESS_INSTRUMENTATION_KEY` in the OTel context for matching requests.

## Logging

`instrument_logging` attaches a Logfire handler to the root logger with `service.name` and `host.name` baked into every record. The fastloom logger uses the standard `logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")`.

## Related

- [Launcher](launcher.md) — the `InitMonitoring(...)` block in the factory.
- [Settings](settings.md) — adding `ObservabilitySettings` to `Settings`.
- [Signals](signals.md) — the rabbit OTel middleware.
