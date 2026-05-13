---
name: add-fastloom-route
description: Use when the user wants to add a new HTTP route, endpoint, or APIRouter to an existing fastloom-based service. Handles auth dependencies, pagination, request/response schemas, and updates app.py to register the new router. Triggers on "add a route", "new endpoint", "scaffold a router".
---

# Add a new route to a fastloom service

Scaffold a FastAPI router that follows the project's conventions, wire it into `app.py`, and produce the matching request/response schemas.

## Detect the project structure

Look for these files at `cwd`:

- `app.py` — must export `app: fastloom.launcher.schemas.App`. Read it to find the `routes=[...]` list and any module aliases.
- `settings.py` — confirm `TC: type[Configs[Settings, TenantSettings]] = Configs` or similar.
- An `api/` (or similar) package — routers usually live there. If multiple naming conventions exist (e.g. `<pkg>/api/`), follow whichever is already in use.

If the project doesn't look like a fastloom service, ask the user to confirm before continuing.

## Gather requirements

Ask in one round:

1. **Route prefix** (e.g. `/users`).
2. **Tag** for OpenAPI grouping (e.g. `"Users"`).
3. **Auth mode** — `required` (default), `optional`, `public`.
4. **Operations needed** — multi-select: `GET (list with pagination)`, `GET /{id}`, `POST (create)`, `PATCH /{id}`, `DELETE /{id}`.
5. **Resource name** (singular, e.g. `User`) so schemas can be named `<Resource>In`, `<Resource>Out`, `<Resource>SearchIn`.

## Generate

### `<pkg>/api/<resource>.py`

```python
from typing import Annotated
from fastapi import APIRouter, Depends, Query
from fastloom.auth.schemas import UserClaims
from fastloom.db.schemas import BasePaginationQuery, PaginatedResponse

from settings import TC
from <pkg>.schemas.<resource> import <Resource>In, <Resource>Out, <Resource>SearchIn

router = APIRouter()


@router.get("", response_model=PaginatedResponse[<Resource>Out])
async def list_<resource>s(
    query: Annotated[<Resource>SearchIn, Query()],
    claims: Annotated[UserClaims, Depends(TC.auth.get_claims)],
) -> PaginatedResponse[<Resource>Out]:
    ...
```

- For required auth: `Annotated[UserClaims, Depends(TC.auth.get_claims)]`.
- For optional auth: `Annotated[UserClaims | None, Depends(TC.optional_auth.get_claims)]`.
- For public: no auth dep at all.
- Use `BasePaginationQuery` for list endpoints; return `PaginatedResponse[T]`.
- Raise `fastloom.i18n.base.DoesNotExist(_("<Resource>"))` for 404s — let the launcher's i18n handler produce the response shape.

### `<pkg>/schemas/<resource>.py`

```python
from pydantic import BaseModel, Field
from fastloom.db.schemas import BasePaginationQuery


class <Resource>In(BaseModel):
    name: str


class <Resource>Out(<Resource>In):
    id: str


class <Resource>SearchIn(BasePaginationQuery):
    name: str | None = None
```

Use **`BeforeValidator` / `AfterValidator` / `model_validator(mode="after")` / `validation_alias`** for anything beyond plain fields — do not write post-ingestion `if …:` checks in the handler.

### `app.py` update

Add an import for the new router and a new tuple to the `routes=[...]` list:

```python
from <pkg>.api import <resource>

routes = [
    ...
    (<resource>.router, "/<resource>s", "<Tag>"),
]
```

If `app.py` doesn't have an explicit `routes` list and uses a different shape, follow that shape.

## Rules to follow

- **No `Any`**, no `dict.get`, no `getattr` on typed shapes.
- **Auth is `Depends(TC.auth.get_claims)` / `TC.optional_auth.get_claims`** — never roll your own JWT parsing.
- **Errors map to HTTP at the route layer**, not in repo/service code. Use `fastloom.i18n.base.CustomI18NException` subclasses or raise the built-in `DoesNotExist`, `OnlyOwnerAllowed`, etc.
- **One pydantic file per resource** under `schemas/`. No business logic there.
- **Validate at the schema, not in the handler** — pull `model_validator`, `BeforeValidator`, `AliasChoices` upstream.

## Verify

After writing files:

1. Run the project's linter (`poetry run ruff check .` or whatever is configured).
2. Run mypy if available.
3. Smoke-test with `launch` and `curl <prefix>/<resource>s`.
