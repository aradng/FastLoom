# Database (MongoDB / Beanie)

Fastloom uses Beanie as the MongoDB ODM. The launcher auto-discovers `Document` / `View` / `UnionDoc` subclasses from `App.models_module`, initializes Beanie, and exposes pagination helpers and timestamp mixins.

**Symbols at a glance**

- `fastloom.db.lifehooks.init_db`, `get_models`, `get_mongo_client`, `destroy_db`.
- `fastloom.db.schemas.CreatedAtSchema`, `CreatedUpdatedAtSchema` — timestamp mixins.
- `fastloom.db.schemas.BasePaginationQuery`, `PaginatedResponse[T]` — pagination contracts.
- `fastloom.db.schemas.BaseTenantSettingsDocument` — backing collection for per-tenant settings (Settings collection name: `settings`).
- `fastloom.db.signals.BaseDocumentSignal`, `SignalsInsert`, `SignalsUpdate`, `SignalsDelete`, `SignalsAll`, `SignalMessage`, `Operations` — auto-publish CRUD events.
- `fastloom.db.settings.MongoSettings` — `MONGO_URI`, `MONGO_DATABASE`.

## Setup

Add `MongoSettings` to your `Settings` and point `App.models_module` at a Python package containing one module per Beanie document:

```python
# my_service/models/__init__.py
# (empty — submodules are auto-imported)

# my_service/models/user.py
from beanie import Document
from pydantic import Field
from fastloom.db.schemas import CreatedUpdatedAtSchema
from fastloom.tenant.schemas import TenantMixin


class User(Document, TenantMixin, CreatedUpdatedAtSchema):
    class Settings:
        name = "users"

    username: str
    display_name: str = Field(default="")
```

```python
# app.py
from my_service import models
from fastloom.launcher.schemas import App

app = App(models_module=models, ...)
```

`fastloom.db.lifehooks.get_models` walks the package via `pkgutil.iter_modules`, picks every class that subclasses `Document`/`View`/`UnionDoc`, and hands them to `init_beanie`. The tenant settings document is appended automatically.

## Timestamp mixins

```python
class CreatedAtSchema(BaseModel):
    created_at: datetime = Field(default_factory=utcnow)


class CreatedUpdatedAtSchema(CreatedAtSchema):
    updated_at: datetime | None = Field(default_factory=utcnow)

    @before_event(Insert, Replace, SaveChanges, Update)
    async def update_updated_at(self):
        self.updated_at = utcnow()
```

`CreatedUpdatedAtSchema` only works on `beanie.Document` subclasses (it uses `@before_event`). **`update_many()` bypasses the hook** — if you batch-update through the raw mongo client, set `updated_at` yourself.

`utcnow()` lives in `fastloom.date`; always use it instead of the deprecated naive `datetime.utcnow()`.

## Pagination

```python
class BasePaginationQuery(BaseModel):
    offset: int | None = Field(None, ge=0)
    limit: int | None = Field(None, ge=0)

    @computed_field
    @property
    def skip(self) -> int | None:
        if self.limit and self.offset is not None:
            return self.limit * self.offset
        return None


class PaginatedResponse[T](BaseModel):
    data: list[T] = []
    count: int = 0
```

`offset` is a **page number**, not a document count. `skip` (computed) gives you the document count to feed into Mongo. A `limit=0` is normalized to `None` so callers can disable pagination explicitly.

```python
from typing import Annotated
from fastapi import APIRouter, Query
from fastloom.db.schemas import BasePaginationQuery, PaginatedResponse

router = APIRouter()


class UserSearchIn(BasePaginationQuery):
    role: str | None = None


@router.get("/", response_model=PaginatedResponse[UserOut])
async def list_users(query: Annotated[UserSearchIn, Query()]) -> PaginatedResponse[UserOut]:
    find = User.find(User.role == query.role) if query.role else User.find()
    total = await find.count()
    items = await find.skip(query.skip).limit(query.limit).to_list()
    return PaginatedResponse(data=items, count=total)
```

## Auto-streamed document signals

`BaseDocumentSignal` ties Beanie state-management hooks to RabbitMQ. Subclass the variant matching the operations you want to publish:

```python
from fastloom.db.signals import SignalsAll
from fastloom.tenant.schemas import TenantMixin


class Order(SignalsAll, TenantMixin):
    class Settings:
        name = "orders"

    item: str
    quantity: int
```

After `init_streams()` (called by the launcher), every `Order.insert()` / `replace()` / `save_changes()` / `update()` / `delete()` publishes a `SignalMessage[Order]` to the topic `{PROJECT_NAME}.orders.{create|update|delete}` via the rabbit topic exchange `amq.topic`.

Each model variant publishes the matching subset:

- `SignalsInsert` → `CREATE` on `@after_event(Insert)`.
- `SignalsUpdate` → `UPDATE` on `@after_event(Replace, SaveChanges, Update, Save)`.
- `SignalsDelete` → `DELETE` on `@after_event(Delete)`.
- `SignalsAll` → all three.

`SignalMessage` carries:

```python
class SignalMessage[T: Document](BaseModel):
    instance: T
    changes: dict[str, Any]   # from Beanie's previous state
    operation: Operations     # StrEnum: create | update | delete
```

The `_PROJECT_NAME` prefix is set by the launcher from `TC.general.PROJECT_NAME`. Duplicate publishes for the same `(revision_id, operation)` pair are suppressed.

## Per-tenant settings document

`BaseTenantSettingsDocument` (collection `settings`) is the storage backing tenant overrides. The launcher dynamically derives a tenant-specific document class from your `TenantSettings` via `create_model`, so you don't subclass it manually. The Configs singleton uses it through `Configs.tenant_schema.document`.

## Manual init / teardown

For tests or scripts, bypass the launcher:

```python
from fastloom.db.lifehooks import init_db, destroy_db

await init_db(
    database_name="test_db",
    models=[User, Order],
    mongo_uri="mongodb://localhost:27017",
)
# ... do stuff ...
await destroy_db("test_db", [User, Order], "mongodb://localhost:27017")
```

`destroy_db` drops the listed collections by default; pass `drop_database=True` to drop the whole DB.

## Related

- [Signals](signals.md) — consuming the auto-published events.
- [Tenant](tenant.md) — `TenantMixin` and tenant-scoped queries.
- [Healthcheck](healthcheck.md) — the auto-registered Mongo ping.
