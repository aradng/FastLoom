# Signals (RabbitMQ)

Fastloom wraps FastStream's `RabbitRouter` in a singleton (`RabbitSubscriber`) that registers publishers, subscribers, a dead-letter-exchange-based retry topology, and OpenTelemetry trace propagation. Document-level CRUD events flow through this same broker via `BaseDocumentSignal` — see [db.md](db.md).

**Symbols at a glance**

- `fastloom.signals.depends.RabbitSubscriber` — singleton; classmethods `subscriber`, `publisher`, `multi_subscriber`, `multi_publisher`.
- `fastloom.signals.depends.RabbitSubscriptable` — settings composite (`MonitoringSettings + RabbitmqSettings`).
- `fastloom.signals.depends.get_rabbit_router` — bare router factory used internally.
- `fastloom.signals.settings.RabbitmqSettings` — `RABBIT_URI` (AMQP DSN).
- `fastloom.signals.healthcheck.get_healthcheck`, `check_rabbit_connection`.
- `fastloom.signals.middlewares.RabbitPayloadTelemetryMiddleware` — OTel span enrichment.
- `fastloom.signals.lifehooks.init_signals`, `init_streams`.

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

`init_signals` recursively imports subpackages so FastStream sees every `@RabbitSubscriber.subscriber(...)` decorator. The launcher then includes `RabbitSubscriber.router` in the FastAPI app so AsyncAPI docs render at `{API_PREFIX}/asyncapi`.

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

## Related

- [db.md](db.md) — `BaseDocumentSignal` auto-publishes to the same broker.
- [Observability](observability.md) — Rabbit instrumentation and queue-name filtering.
- [Healthcheck](healthcheck.md) — broker ping registration.
