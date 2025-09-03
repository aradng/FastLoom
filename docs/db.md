# Database (MongoDB / Beanie)

Core provides helpers and conventions for Beanie ODM.

- `core_bluprint.db.lifehooks.init_db()` initializes the database and registers models.
- `core_bluprint.db.schemas` contains reusable mixins and helpers:
  - `CreatedAtSchema`, `CreatedUpdatedAtSchema` — timestamp fields and hooks
  - `BaseDocument`, `BaseTenantSettingsDocument` — typed id accessors and helpers
  - `BasePaginationQuery`, `PaginatedResponse[T]` — query and response helpers

Pagination example:

```python
from core_bluprint.db.schemas import BasePaginationQuery

class ListQuery(BasePaginationQuery):
    # add filters here
    pass
```

See also: `core_bluprint/launcher/schemas.py` for model discovery via `App.models_module`.
