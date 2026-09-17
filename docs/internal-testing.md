# Internal testing

This is about testing **fastloom itself** — the `tests/` directory at the
repo root, run via `poetry run pytest` in CI. It's a different thing from
[test.md](test.md), which documents the fixture package fastloom *ships* for
consuming services to test *their own* code.

Each capability's tests live under `tests/<capability>/` (e.g. `tests/kafka/`)
with their own `conftest.py` — mirrors the `fastloom/<capability>/` layout.

## Kafka

`tests/kafka/conftest.py` sets a `TracerProvider` with an in-memory exporter
at **module import time**:

```python
trace.set_tracer_provider(_provider)
```

`trace.set_tracer_provider` is one-shot — OpenTelemetry keeps the first
provider set and only logs a warning on any later call. Nothing else in the
suite sets one today, but a test that exercises `InitMonitoring` or
`instrument_otel` for real would race this, and the loser's exporter goes
silent without failing anything.

There is no import-order constraint any more. Kafka spans come from
FastStream's `KafkaTelemetryMiddleware`, attached inside `get_kafka_router()`
and resolving its tracer when a span starts, so a `KafkaSubscriber` may be
constructed whenever it suits the test. The shared `kafka_subscriber` fixture
passes settings with `OTEL_ENABLED=1`, which means every Kafka test exercises
the middleware — that is deliberate, and is how a tombstone regression inside
it was caught.
