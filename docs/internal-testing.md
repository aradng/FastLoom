# Internal testing

This is about testing **fastloom itself** — the `tests/` directory at the
repo root, run via `poetry run pytest` in CI. It's a different thing from
[test.md](test.md), which documents the fixture package fastloom *ships* for
consuming services to test *their own* code.

Each capability's tests live under `tests/<capability>/` (e.g. `tests/kafka/`)
with their own `conftest.py` — mirrors the `fastloom/<capability>/` layout.

## Kafka

`tests/kafka/conftest.py` instruments `confluent-kafka` at **module import
time**, before any fixture or test body runs:

```python
ConfluentKafkaInstrumentor().instrument(tracer_provider=_provider)
```

This has to happen before the first *construction* of a `KafkaSubscriber` (or
call to `get_kafka_router()`) anywhere in the process — not before importing
`fastloom.signals.kafka` itself, which is import-order-safe (see
[signals.md](signals.md#ordering)). `KafkaSubscriber`
construction is what triggers `faststream.confluent`'s internal
`from confluent_kafka import Producer` — `ConfluentKafkaInstrumentor` patches
those classes at the class level, so a construction that happens before
instrumentation binds the unpatched ones, and instrumenting after that point
is a permanent no-op for the rest of the process.

Every `KafkaSubscriber(...)` construction in `tests/kafka/` is deferred into
a fixture or test body for exactly this reason — conftest's module-level
instrumentation always runs first in pytest's collection order, regardless
of which test file happens to execute first.
