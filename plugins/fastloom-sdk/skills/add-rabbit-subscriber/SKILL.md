---
name: add-rabbit-subscriber
description: Use when the user wants to add a RabbitMQ subscriber, broker consumer, or signal handler to an existing fastloom service. Handles signals_module discovery, payload schema, retry/backoff configuration, and DLX-aware error semantics. Triggers on "add a subscriber", "consume a queue", "listen to a routing key", "handle a broker message".
---

# Add a RabbitMQ subscriber to a fastloom service

Scaffold a FastStream subscriber via `RabbitSubscriber.subscriber`, wire it into the project's `signals_module`, and produce the matching payload schema.

## Detect

Look for:

- `app.py` with `signals_module=<pkg>.signals` (or similar). Read it; if absent, the project may not have rabbit configured — confirm with the user before continuing.
- `<pkg>/signals/` (or wherever signals live). Subscribers typically go under `<pkg>/signals/consumer/<domain>.py`; publishers under `<pkg>/signals/producer.py`. Follow whatever layout already exists.
- `tenants.yaml` should have `RABBIT_URI` under `default:`. If not, ask the user to populate it before testing.

## Gather requirements

Ask in one round:

1. **Routing key** (the bound topic key — e.g. `acme.user.created`).
2. **Payload schema** — name and fields (e.g. `UserCreated { user_id: UUID, email: str }`), or "use an existing schema" with the import path.
3. **Retry behavior** — `retry_backoff=True` (default for production work) or `False`.
4. **Domain name** for file placement (used as `<pkg>/signals/consumer/<domain>.py`).

## Generate

### `<pkg>/schemas/<domain>.py` (only if a new schema is needed)

```python
from pydantic import BaseModel
from uuid import UUID


class UserCreated(BaseModel):
    user_id: UUID
    email: str
```

If the payload needs alias mapping (e.g. broker uses `bucket` but the field is `tenant`), use `Field(validation_alias="bucket")` — do not patch the dict in the handler.

### `<pkg>/signals/consumer/<domain>.py`

```python
import logging
from fastloom.signals.rabbit.depends import RabbitSubscriber

from <pkg>.schemas.<domain> import UserCreated

logger = logging.getLogger(__name__)


@RabbitSubscriber.subscriber(
    routing_key="acme.user.created",
    retry_backoff=True,
)
async def on_user_created(payload: UserCreated) -> None:
    logger.info("user created", extra={"user_id": str(payload.user_id)})
    # business logic here
```

### Wire into `signals_module`

If `<pkg>/signals/consumer/__init__.py` doesn't exist, create it (empty file is fine — `init_signals` walks subpackages). The `App(signals_module=signals)` declaration in `app.py` should already point at the parent package; no edit needed unless the package wasn't wired yet.

## Rules to follow

- **`retry_backoff=True` requires `durable=True` and `auto_delete=False`** (both are the default). Don't override them.
- **Subscriber name doesn't matter for FastStream**, but file location does — `init_signals` only walks subpackages, so handlers must live under a package (folder with `__init__.py`), not a sibling module.
- **Payload type drives validation** — never accept `dict` and validate inside the body. The whole point is pydantic at the broker boundary.
- **Idempotency is your job** — RabbitMQ DLX can redeliver. If your handler isn't idempotent, dedupe on a stable key from the payload (e.g. `payload.user_id`).
- **Use `fastloom.signals.rabbit.depends.RabbitSubscriber.publisher(...)`** to send messages back; don't construct `aio_pika` clients manually.
- **The handler can `raise`** — fastloom's exception middleware republishes to a delay queue with exponential backoff (5s → 10s → 20s → … up to 24h by default). The exception is re-raised after requeue for Sentry/OTel.

## Verify

1. Confirm the rabbit container is running: `docker compose ps rabbitmq` (or whatever local broker the project uses).
2. Restart the service: `launch` (or `docker compose restart <service>`).
3. Publish a test message from a Python REPL or `rabbitmqadmin`:
   ```python
   import asyncio
   from <pkg>.signals.producer import some_publisher  # if there's a matching publisher
   asyncio.run(some_publisher.publish({...}))
   ```
4. Check service logs for the expected handler invocation.
