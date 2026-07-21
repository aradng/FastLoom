---
name: add-kafka-subscriber
description: Use when the user wants to add a Kafka subscriber, topic consumer, or Debezium/CDC handler to an existing fastloom service. Handles KafkaSettings wiring, payload schema, ack_policy/retry-backoff configuration, and the poll-loop-blocking gotcha. Triggers on "add a kafka subscriber", "consume a kafka topic", "listen to a topic", "handle a CDC event".
---

# Add a Kafka subscriber to a fastloom service

Scaffold a FastStream subscriber via `KafkaSubscriber.router.subscriber`, wire it into the project's `signals_module`, and produce the matching payload schema.

## Detect

Look for:

- `app.py` with `signals_module=<pkg>.signals` (or similar). Read it; if absent, the project may not have kafka configured — confirm with the user before continuing.
- `<pkg>/signals/` (or wherever signals live). Subscribers typically go under `<pkg>/signals/consumer/<domain>.py`; publishers under `<pkg>/signals/producer.py`. Follow whatever layout already exists.
- `tenants.yaml` should have `KAFKA_URI` under `default:`. If not, ask the user to populate it before testing.
- If the service also uses `RabbitmqSettings`, both brokers coexist fine — `signals_module` accepts subscribers for either.

## Gather requirements

Ask in one round:

1. **Topic name** (e.g. `my_service.order.create`, or a CDC topic like `debezium.public.orders`).
2. **Payload schema** — name and fields, or "use an existing schema" with the import path.
3. **`group_id`** — the consumer group (usually the service name).
4. **Retry behavior** — rely on the broker-wide `NACK_ON_ERROR` default (recommended), or does this specific subscriber need `ack_policy="ack_first"` (fire-and-forget, no redelivery, no backoff)?
5. **Domain name** for file placement (used as `<pkg>/signals/consumer/<domain>.py`).

## Generate

### `<pkg>/schemas/<domain>.py` (only if a new schema is needed)

```python
from pydantic import BaseModel
from uuid import UUID


class OrderCreated(BaseModel):
    order_id: UUID
    user_id: UUID
```

If the payload needs alias mapping, use `Field(validation_alias="...")` — do not patch the dict in the handler.

### `<pkg>/signals/consumer/<domain>.py`

```python
import logging
from fastloom.signals.kafka.depends import KafkaSubscriber

from <pkg>.schemas.<domain> import OrderCreated

logger = logging.getLogger(__name__)


@KafkaSubscriber.router.subscriber(
    "my_service.order.create",
    group_id="my_service",
    auto_offset_reset="earliest",
)
async def on_order_create(payload: OrderCreated) -> None:
    logger.info("order created", extra={"order_id": str(payload.order_id)})
    # business logic here
```

### Wire into `signals_module`

If `<pkg>/signals/consumer/__init__.py` doesn't exist, create it (empty file is fine — `init_signals` walks subpackages). The `App(signals_module=signals)` declaration in `app.py` should already point at the parent package; no edit needed unless the package wasn't wired yet.

## Rules to follow

- **Use `KafkaSubscriber.router.subscriber(...)` directly** — there's no `KafkaSubscriber.subscriber(...)` wrapper like Rabbit has (Kafka has topics, not exchanges/queues, so there's no naming indirection to hide). Same for publishing: `KafkaSubscriber.router.publisher("topic.name")`.
- **`auto_offset_reset` has no broker-wide default** — pass it on every `@subscriber(...)` call that needs it (usually `"earliest"` for CDC/event-sourcing consumers that must not miss history).
- **`KafkaSubscriber`'s constructor already defaults `ack_policy=NACK_ON_ERROR` broker-wide** — a subscriber whose handler raises gets exponential backoff (5s → 10s → ... capped at 4min by default, with jitter) for free. Only pass `ack_policy="ack_first"` on a specific `@subscriber(...)` call if that handler genuinely wants fire-and-forget semantics (no redelivery, no backoff) — that subscriber's exceptions just propagate without a retry.
- **The backoff sleep blocks that subscriber's whole poll loop** — every partition/topic it owns, not just the failing one — since the loop can't poll again until the current handler (and the sleep) returns. Don't reach for `max_workers>1` to work around this: `KafkaMessage.ack()` commits the consumer's current position, not a specific offset, so a concurrent handler acking a later offset can commit past an earlier one still asleep in backoff, and a crash in that window permanently skips it. If `max_delay` needs to go higher than the default, raise `max.poll.interval.ms` on the affected `@subscriber(...)` call to match (FastStream's own default there is 5 minutes) or the consumer gets rebalanced mid-backoff instead.
- **Payload type drives validation** — never accept `dict` and validate inside the body.
- **Idempotency is your job** — a redelivered message reprocesses. If your handler isn't idempotent, dedupe on a stable key from the payload.
- **Batch consumers** (`batch=True`) collapse retry tracking to the first message's offset — if you need per-message retry granularity, don't use batch mode with backoff-sensitive handlers.

## Verify

1. Confirm the kafka container is running: `docker compose ps kafka` (or whatever local broker the project uses).
2. Restart the service: `launch` (or `docker compose restart <service>`).
3. Produce a test message from a Python REPL or `kcat`:
   ```python
   import asyncio
   from <pkg>.signals.producer import some_publisher  # if there's a matching publisher
   asyncio.run(some_publisher.publish({...}))
   ```
4. Check service logs for the expected handler invocation.
