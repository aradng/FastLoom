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

The launcher constructs `RabbitSubscriber(TC.general)` **before** `InitMonitoring`, so aio-pika OTel instrumentation attaches to the broker (`TC.general` satisfies the `RabbitSubscriptable` protocol because your `Settings` inherits both `MonitoringSettings` and `RabbitmqSettings`).

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

The launcher includes `KafkaSubscriber.router` in the FastAPI app so AsyncAPI docs render at `{API_PREFIX}/kafkaapi`.

### Rabbit and Kafka AsyncAPI docs live at different paths

A service using both `RabbitSubscriber` and `KafkaSubscriber` (a hybrid signals setup) gets two independent AsyncAPI documents — Rabbit's at `{API_PREFIX}/rabbitapi`, Kafka's at `{API_PREFIX}/kafkaapi` — never a merged one. FastStream's `AsyncAPI` specification factory (`faststream.specification.asyncapi.factory`) has partial scaffolding for multiple brokers (`add_broker()`, a `self.brokers` list), but `to_specification()` only ever renders `self.brokers[0]`, and the underlying schema generators (`get_broker_server`/`get_broker_channels`) each take a single broker — there's no version of FastStream today that can produce one combined multi-broker document. Each `StreamRouter` (`RabbitRouter`/`KafkaRouter`) mounts its own 3-route docs sub-router (`GET {schema_url}`, `.json`, `.yaml`) onto the parent app at ASGI-lifespan-startup, purely additively, with **no path-collision check** — if both routers ever computed the same `schema_url`, both sets of routes would silently coexist in the route table and Starlette's first-match-wins matching would permanently shadow whichever was included second, with no error or warning anywhere. `get_rabbit_router`/`get_kafka_router` give each broker a distinct path specifically to avoid this.

### Ordering is reversed from Rabbit

`RabbitSubscriber` is constructed **before** `InitMonitoring` (so `AioPikaInstrumentor` attaches before the connection opens). `KafkaSubscriber` is constructed **after** `InitMonitoring` enters — the opposite order. `ConfluentKafkaInstrumentor` patches `confluent_kafka.Producer`/`Consumer` at the class level, and FastStream's confluent client does `from confluent_kafka import Producer` at *import* time; constructing a `KafkaSubscriber` (which triggers that import internally) before instrumentation runs would bind the unpatched classes permanently for the process.

Note this is about **construction**, not the top-level `import fastloom.signals.kafka.depends` statement — `kafka.depends` defers its own `faststream.confluent` import into `get_kafka_router()`'s body specifically so the module itself can be imported eagerly (same as `RabbitSubscriber`) without tripping the ordering constraint. This is handled for you inside the launcher — just know that if you construct `KafkaSubscriber` yourself outside the launcher (e.g. a standalone script), instrument first.

### Telemetry caveat

`Instruments.KAFKA` (`instrument_confluent_kafka`) is auto-inferred from `KafkaSettings` like Rabbit's is from `RabbitmqSettings`. It requires `opentelemetry-instrumentation-confluent-kafka>=0.62b1,<0.64b0` (pinned in the `kafka` extra) — below `0.62b1`, the bundled instrumentor doesn't forward the `logger` kwarg FastStream's consumer always passes and **crashes on subscriber startup**; `0.64b0`+ needs a newer `opentelemetry-sdk` than `logfire` currently supports. Don't loosen this pin without re-verifying both failure modes.

There's no Kafka equivalent of `RabbitPayloadTelemetryMiddleware` — Kafka spans get producer/consumer-level tracing from `ConfluentKafkaInstrumentor` (send/recv/process spans), but not the payload-header propagation enrichment Rabbit's middleware adds.

## Related

- [db.md](db.md) — `BaseDocumentSignal` auto-publishes to the same broker.
- [Observability](observability.md) — Rabbit/Kafka instrumentation and queue-name filtering.
- [Healthcheck](healthcheck.md) — broker ping registration.
