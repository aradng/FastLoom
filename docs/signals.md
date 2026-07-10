# Signals (RabbitMQ / Kafka)

Fastloom wraps FastStream's `RabbitRouter` in a singleton (`RabbitSubscriber`) that registers publishers, subscribers, a dead-letter-exchange-based retry topology, and OpenTelemetry trace propagation. Document-level CRUD events flow through this same broker via `BaseDocumentSignal` — see [db.md](db.md).

A separate, thinner singleton (`KafkaSubscriber`) wraps FastStream's confluent-kafka `KafkaRouter` for services that consume Kafka topics (e.g. Debezium CDC streams, or a third party's own topic) — see [Kafka](#kafka) below.

**Symbols at a glance**

- `fastloom.signals.depends.RabbitSubscriber` — singleton; classmethods `subscriber`, `publisher`, `multi_subscriber`, `multi_publisher`.
- `fastloom.signals.depends.RabbitSubscriptable` — settings composite (`MonitoringSettings + RabbitmqSettings`).
- `fastloom.signals.depends.get_rabbit_router` — bare router factory used internally.
- `fastloom.signals.settings.RabbitmqSettings` — `RABBIT_URI` (AMQP DSN).
- `fastloom.signals.healthcheck.get_healthcheck`, `check_rabbit_connection`.
- `fastloom.signals.middlewares.RabbitPayloadTelemetryMiddleware` — OTel span enrichment.
- `fastloom.signals.lifehooks.init_signals`, `init_streams`.
- `fastloom.signals.kafka.depends.KafkaSubscriber` — singleton; owns `router: KafkaRouter` only.
- `fastloom.signals.kafka.depends.get_kafka_router` — bare router factory used internally.
- `fastloom.signals.kafka.settings.KafkaSettings`, `KafkaSubscriptable` — `KAFKA_URI`.
- `fastloom.signals.kafka.schemas.KafkaBootstrapServers` — the `KAFKA_URI` type; `.servers` gives the parsed `list[str]`.
- `fastloom.signals.kafka.healthcheck.get_healthcheck`, `check_kafka_connection`.

## Wiring

Add `RabbitmqSettings` to your `Settings` and set `App.signals_module` to a Python package whose subpackages hold subscriber modules:

```
my_service/
    signals/
        __init__.py
        producer.py           # publishers
        consumer/
            __init__.py
            order.py          # subscribers
            user.py
```

```python
# app.py
from my_service import signals
from fastloom.launcher.schemas import App

app = App(signals_module=signals, ...)
```

`init_signals` recursively imports subpackages so FastStream sees every `@RabbitSubscriber.subscriber(...)` decorator. The launcher then includes `RabbitSubscriber.router` in the FastAPI app so AsyncAPI docs render at `{API_PREFIX}/rabbitapi`.

The launcher calls `init_early_monitoring(TC.general)` (Sentry init + broker instrumentation) then constructs `RabbitSubscriber(TC.general)` — both **before** `get_app()`/`InitMonitoring` — so aio-pika OTel instrumentation attaches to the broker before anything else runs (`TC.general` satisfies the `RabbitSubscriptable` protocol because your `Settings` inherits both `MonitoringSettings` and `RabbitmqSettings`). `KafkaSubscriber` constructs at the same point, right after — see [Ordering](#ordering) below.

## Publishers

```python
# signals/producer.py
from pydantic import BaseModel
from fastloom.signals.depends import RabbitSubscriber


class NotificationOut(BaseModel):
    user_id: str
    message: str


notification_publisher = RabbitSubscriber.publisher(
    routing_key="notify.notification.schedule",
    schema=NotificationOut,
)


# later, anywhere:
await notification_publisher.publish(
    NotificationOut(user_id="u1", message="hello"),
)
```

`publisher` returns a FastStream `RabbitPublisher` bound to the topic exchange `amq.topic`. Pass `persist=False` for transient messages, `mandatory=False` to skip the broker-side return.

`multi_publisher(routing_keys=dict[str, str], ...)` returns `{name: RabbitPublisher}` — useful for fan-out style code where you want named handles to several topics.

## Subscribers

```python
# signals/consumer/order.py
from fastloom.signals.depends import RabbitSubscriber

from my_service.schemas import OrderSignal


@RabbitSubscriber.subscriber(
    routing_key="my_service.order.create",
    retry_backoff=True,
)
async def on_order_create(payload: OrderSignal) -> None:
    ...
```

Subscriber options:

| Option | Default | Effect |
|--------|---------|--------|
| `routing_key` | required | Topic routing key bound to `amq.topic`. |
| `retry_backoff` | `False` | Enables exponential-backoff retry via dead-letter queues (see below). Requires `durable=True` and `auto_delete=False`. |
| `durable` | `True` | Queue survives broker restart. |
| `auto_delete` | `False` | Queue is deleted when the last consumer disconnects. |
| `queue_arguments` | `None` | Classic / Quorum / Stream queue args (`x-...`). |
| `**kwargs` | — | Forwarded to FastStream's `router.subscriber`. |

Queue names are prefixed with `{ENVIRONMENT}_{PROJECT_NAME}` — so two services or two environments sharing a broker don't collide. Wildcards (`*`) in routing keys are sanitized to `__all__` in the queue name.

`multi_subscriber(routing_keys=[...], ...)` applies the same handler to several routing keys.

## Retry / backoff topology

When `retry_backoff=True`, the subscriber also binds a parallel dead-letter queue named `{queue_name}.{PROJECT_NAME}`. Failed messages (any unhandled exception in the handler) are republished into a delay queue with TTL `min(base_delay * 2 ** attempt, max_delay)` and routed back to the original DLX. Delay queues are created lazily via a side topology channel guarded by an asyncio lock.

Defaults on `RabbitSubscriber(settings, base_delay=5, max_delay=86400)`:

- `base_delay=5` seconds — first retry waits 5s, then 10s, 20s, 40s, …
- `max_delay=86400` seconds — caps at 24h.

The handler's exception is re-raised after the requeue so Sentry / OTel record the failure.

## Telemetry

`RabbitPayloadTelemetryMiddleware` extracts OTel propagators from message headers and starts spans named after the routing key. Publish-side propagation is handled by `aio-pika`'s instrumentation, which the launcher enables via `Instruments.RABBIT` (auto-inferred from `RabbitmqSettings`).

## Healthcheck

`fastloom.signals.healthcheck.get_healthcheck(router)` returns an async callable that pings the broker (timeout 5s). The launcher registers it automatically when `signals_module` is set; no manual wiring needed.

## Kafka

Add `KafkaSettings` to your `Settings` (it can coexist with `RabbitmqSettings` — `signals_module` accepts either, or both):

```python
class Settings(KafkaSettings, RabbitmqSettings, ...):
    ...
```

`KAFKA_URI` takes librdkafka's bare `host:port[,host:port]` bootstrap-server form. A `kafka://` prefix is accepted and stripped for convenience (`kafka://broker:9092` → `broker:9092`); malformed input raises a validation error rather than silently passing through.

Unlike `RabbitSubscriber`, `KafkaSubscriber` is a **thin** wrapper — it only owns `router: KafkaRouter` construction. There's no exchange/queue-naming indirection to hide (Kafka has topics, not exchanges), so declare subscribers and publishers straight off the router:

```python
# signals/consumer/order.py
from fastloom.signals.kafka.depends import KafkaSubscriber


@KafkaSubscriber.router.subscriber(
    "my_service.order.create",
    group_id="my_service",
    auto_offset_reset="earliest",
)
async def on_order_create(payload: OrderSignal) -> None:
    ...


order_publisher = KafkaSubscriber.router.publisher("my_service.order.create")
```

Everything FastStream's confluent router supports — `batch`, `ack_policy`, multiple topics per subscriber, etc. — is available directly; fastloom doesn't wrap it. There's no DLX-style retry/backoff (Kafka's append-only log with consumer-group offsets doesn't map onto Rabbit's per-message delay-queue model, and no real consumer has needed it — they NACK-and-move-on via FastStream's own `ack_policy`).

`KafkaSubscriber` can't subclass `KafkaRouter` directly to drop the `.router.` indirection — `SelfSustainingMeta` only proxies attribute names that are *missing* from the class (via `__getattr__`); inheriting from `KafkaRouter` would make its methods present via normal MRO lookup, so `KafkaSubscriber.subscriber` would resolve to the raw unbound function instead of routing through the singleton, breaking at call time. A classmethod-forwarding wrapper (`KafkaSubscriber.subscriber(...)` delegating to `cls.router.subscriber(...)`) was tried and works, but degrades the call site's type information to `Any` for no real benefit over `KafkaSubscriber.router.subscriber(...)`, so it was dropped.

The launcher includes `KafkaSubscriber.router` in the FastAPI app so AsyncAPI docs render at `{API_PREFIX}/kafkaapi`.

### Rabbit and Kafka AsyncAPI docs live at different paths

A service using both `RabbitSubscriber` and `KafkaSubscriber` (a hybrid signals setup) gets two independent AsyncAPI documents — Rabbit's at `{API_PREFIX}/rabbitapi`, Kafka's at `{API_PREFIX}/kafkaapi` — never a merged one. FastStream's `AsyncAPI` specification factory (`faststream.specification.asyncapi.factory`) has partial scaffolding for multiple brokers (`add_broker()`, a `self.brokers` list), but `to_specification()` only ever renders `self.brokers[0]`, and the underlying schema generators (`get_broker_server`/`get_broker_channels`) each take a single broker — there's no version of FastStream today that can produce one combined multi-broker document. Each `StreamRouter` (`RabbitRouter`/`KafkaRouter`) mounts its own 3-route docs sub-router (`GET {schema_url}`, `.json`, `.yaml`) onto the parent app at ASGI-lifespan-startup, purely additively, with **no path-collision check** — if both routers ever computed the same `schema_url`, both sets of routes would silently coexist in the route table and Starlette's first-match-wins matching would permanently shadow whichever was included second, with no error or warning anywhere. `get_rabbit_router`/`get_kafka_router` give each broker a distinct path specifically to avoid this.

### Ordering

`RabbitSubscriber` and `KafkaSubscriber` both construct **before** `get_app()`/`InitMonitoring` — the launcher calls `init_early_monitoring(TC.general)` first, then constructs whichever of the two subscribers apply. `init_early_monitoring` initializes Sentry (if `SENTRY_ENABLED`) and then runs `instrument_brokers` (`AioPikaInstrumentor`/`ConfluentKafkaInstrumentor`, auto-inferred straight from `TC.general` via `infer_broker_instruments`) — both independent of the rest of `InitMonitoring` (FastAPI instrumentation, service-specific `additional_instruments`), because neither needs data from `get_app()`. Sentry goes first so a crash inside broker instrumentation itself is still reported; `init_sentry` is guarded with `sentry_sdk.is_initialized()` so `InitMonitoring.__enter__`'s own (unrelated) `init_sentry` call later doesn't double-initialize it.

This split exists because `ConfluentKafkaInstrumentor` patches `confluent_kafka.Producer`/`Consumer` by reassigning the *module attribute* (`confluent_kafka.Producer = AutoInstrumentedProducer`), not by wrapping methods in place — FastStream's confluent client does `from confluent_kafka import Producer` at *import* time, which copies a reference to whatever class is bound at that moment. If that import happens before the patch, FastStream keeps referring to the unpatched class for the lifetime of the process, no matter when a `Producer` instance actually gets constructed later. (`aio-pika`'s instrumentor doesn't have this problem — `AioPikaInstrumentor` wraps `Queue.consume`/`Exchange.publish` in place on the existing class objects, so it's insensitive to import order; that's the underlying reason Kafka's ordering constraint used to look different from Rabbit's.)

Note this is about when `get_kafka_router()` actually **runs**, not the top-level `import fastloom.signals.kafka.depends` statement — `kafka.depends` defers its own `faststream.confluent` import into `get_kafka_router()`'s body specifically so the module itself can be imported eagerly without tripping the ordering constraint. This is handled for you inside the launcher — just know that if you construct `KafkaSubscriber` yourself outside the launcher (e.g. a standalone script), call `init_early_monitoring` first.

### Telemetry caveat

`Instruments.KAFKA` (`instrument_confluent_kafka`) is auto-inferred from `KafkaSettings` like Rabbit's is from `RabbitmqSettings`. It requires `opentelemetry-instrumentation-confluent-kafka>=0.62b1,<0.64b0` (pinned in the `kafka` extra) — below `0.62b1`, the bundled instrumentor doesn't forward the `logger` kwarg FastStream's consumer always passes and **crashes on subscriber startup**; `0.64b0`+ needs a newer `opentelemetry-sdk` than `logfire` currently supports. Don't loosen this pin without re-verifying both failure modes.

There's no Kafka equivalent of `RabbitPayloadTelemetryMiddleware` — Kafka spans get producer/consumer-level tracing from `ConfluentKafkaInstrumentor` (send/recv/process spans), but not the payload-header propagation enrichment Rabbit's middleware adds.

## Related

- [db.md](db.md) — `BaseDocumentSignal` auto-publishes to the same broker.
- [Observability](observability.md) — Rabbit/Kafka instrumentation and queue-name filtering.
- [Healthcheck](healthcheck.md) — broker ping registration.
