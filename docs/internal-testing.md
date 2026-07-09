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

This has to happen before the first import of `fastloom.signals.kafka` (or
`faststream.confluent`) anywhere in the process. `ConfluentKafkaInstrumentor`
patches `confluent_kafka.Producer`/`Consumer` at the class level, and
FastStream's confluent client does `from confluent_kafka import Producer` at
*import* time — so an earlier import binds the unpatched classes, and
instrumenting after that point is a permanent no-op for the rest of the
process (see [signals.md](signals.md#ordering-is-reversed-from-rabbit) for
the same constraint in the launcher).

Every `fastloom.signals.kafka` import in `tests/kafka/` is deferred into a
fixture or test body for exactly this reason — conftest's module-level
instrumentation always runs first in pytest's collection order, regardless
of which test file happens to execute first.
