---
description: Settings field naming, datetime hygiene, and the Str[T] string-with-validator type
paths: ["**/*.py"]
---

# Naming and types

## Settings field naming

- **Capability fields** (anything from a `*Settings` mixin) use **SCREAMING_SNAKE_CASE**: `MONGO_URI`, `RABBIT_URI`, `REDIS_URL`, `APP_PORT`, `MCP_ENABLED`. They double as env-var names — `fastloom.settings.utils.pydantic_env_or_default` reads from the environment when set.
- **Tenant-scoped, business-domain fields** use **snake_case**: `website_url`, `choice_sources`, `default_profile_type`, `questions`. These are values the tenant owns, not infrastructure knobs.
- **For env-var fallbacks**, use the explicit annotation:
  ```python
  from typing import Annotated
  from pydantic import BeforeValidator
  from fastloom.settings.utils import pydantic_env_or_default

  FIELD: Annotated[str, BeforeValidator(pydantic_env_or_default)] = "default"
  ```
- `EnvBackend[T]` / `EnvDefault` in `fastloom.observability.settings` are the canonical idiom for OTel-style env-backed fields — copy that pattern.

## Datetime

- **Always use `fastloom.date.utcnow()`** for current time. It returns a timezone-aware UTC `datetime`.
- **Never use `datetime.utcnow()`** — deprecated, naive, breaks Mongo's `tz_aware=True` and serialization round-trips.
- Other helpers in `fastloom.date`:
  - `datetime_to_jalali(dt, date_only=False)` — Tehran-zone Jalali formatting.
  - `datetime_to_timestamp(dt)` — UTC unix-seconds int.
  - `get_zero_time()` — midnight of today.

## `Str[T]` string-with-validator

`fastloom.types.Str[T]` is a `str` subclass that runs a pydantic adapter on validate and serializes as a plain string.

Use it whenever you want pydantic to validate a URL/DSN but downstream code (uvicorn args, env vars, `redis.from_url`, `AsyncMongoClient`) needs a plain `str`:

```python
from pydantic import AmqpDsn, HttpUrl, RedisDsn
from fastloom.types import Str

class S(BaseModel):
    MONGO_URI: Str[HttpUrl]      # validated as URL, stored as str
    RABBIT_URI: Str[AmqpDsn]
    REDIS_URL: Str[RedisDsn]
```

## Anti-patterns

- ❌ `mongo_uri: str` (lowercase) in a capability mixin — breaks env-var lookup and the public settings endpoint.
- ❌ `REDIS_URL: AnyUrl` without `Str[...]` — downstream callers get a `Url` object and break.
- ❌ `datetime.now()` without `ZoneInfo` — produces naive local time.
- ❌ Putting infrastructure fields (`MONGO_URI`, broker URIs, secrets) inside `TenantSettings`. They belong on `Settings` and live in `default:` of `tenants.yaml`. Tenants share the database; the `tenant` field on each document partitions the data.
