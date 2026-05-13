# Conventions

Patterns and rules that repeat across the codebase. Follow them when extending the library or building a service against it.

## `Configs.general` — universal settings access

`Configs` (aka `fastloom.tenant.settings.ConfigAlias`) is a class-level singleton built on `SelfSustaining`. After the launcher calls `Configs(Settings, TenantSettings)`, anywhere in the codebase you read service-wide settings via `Configs.general`:

```python
from fastloom.tenant.settings import ConfigAlias as Configs

prefix = Configs.general.API_PREFIX
url = Configs.general.MONGO_URI
```

Most services alias `Configs` as `TC` (tenant configs) in `settings.py` so application code is terser:

```python
# settings.py
from pydantic import BaseModel
from fastloom.tenant.settings import Configs


class Settings(...): ...
class TenantSettings(BaseModel): ...


TC: type[Configs[Settings, TenantSettings]] = Configs
```

Then everywhere else:

```python
from settings import TC

TC.general.API_PREFIX
TC.auth.get_claims
TC.from_[TokenHeaderSource]
```

`TC` is exactly the same singleton as `Configs` — the alias just narrows the generic parameters so mypy knows the field types up front. Pick one alias per project and stick to it.

### `await Configs[tenant_id]` for tenant settings

To resolve **per-tenant** settings (cache → Mongo → YAML), subscript the singleton with a tenant id and await:

```python
tenant_cfg = await Configs["acme"]            # equivalent to: await Configs.get("acme")
print(tenant_cfg.website_url)
```

To **persist** an update, use the explicit method (no `__asetitem__` in Python, so `Configs[id] = value` would not be awaitable):

```python
await Configs.set("acme", tenant_cfg)
```

### Type narrowing

When you need mypy to know that a particular capability is configured, prefer `isinstance` over subscript syntax:

```python
if isinstance(Configs.general, RedisSettings):
    url = Configs.general.REDIS_URL   # narrowed
```

Inside the library itself, you'll see the older `Configs[CapabilitySettings].general` form (using PEP 695 generic subscript). Both compile to the same singleton access — but in user code, plain `Configs.general` (or `TC.general`) is preferred.

## `SelfSustaining` — class-level singletons

`fastloom.meta.SelfSustaining` is the metaclass-driven singleton helper used by `Configs`, `RabbitSubscriber`, and `RedisHandler`. It's worth understanding before touching any of the three.

```python
class SelfSustainingMeta(type):
    def __new__(mcls, name, bases, namespace):
        namespace["self"] = cast(object, None)
        return super().__new__(mcls, name, bases, namespace)

    def __getattr__(cls, name):
        if cls.self is None:
            raise AttributeError(f"{cls.__name__}.self is not initialized")
        return getattr(cls.self, name)

    def __setattr__(cls, name, value):
        ...
        return setattr(cls.self, name, value)


class SelfSustaining(metaclass=SelfSustainingMeta):
    self: Self

    def __init__(self, *args, **kwargs):
        type(self).self = self    # store the instance on the class
```

Three things to remember:

1. **`Cls(...)` constructs the singleton once.** The instance is stored at `Cls.self`. A second `Cls(...)` call may re-enter `__init__`, so check `cls.self is None` early (or `super().__init__()` first) if you need idempotency.
2. **Attribute access on the class forwards to the instance.** `Configs.general` is sugar for `Configs.self.general`. This is what makes the `TC.general` pattern work without ever instantiating a variable.
3. **`Cls.self = None` resets the singleton.** Tests use this to swap settings between cases — see [test.md](test.md).

Subclassing `SelfSustaining`:

```python
from fastloom.meta import SelfSustaining


class MyHandler(SelfSustaining):
    redis: Redis

    def __init__(self, settings):
        super().__init__()        # stores `self` on the class
        self.redis = ...

MyHandler(settings)
MyHandler.redis.get("key")        # forwarded to the singleton
```

Do not instantiate a `SelfSustaining` class more than once per process — the second instance silently replaces the first and any classmethod that captured `cls.self` early is now stale.

## Optional-dependency import pattern

Several capabilities (`mongo`, `rabbit`, `redis`, `mcp`, …) are optional extras. Modules that touch them use this exact shape so type checkers see the real symbol and runtime degrades to a pydantic `BaseModel` stand-in:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from beanie import Document
else:
    try:
        from beanie import Document
    except ImportError:
        from pydantic import BaseModel as Document
```

Pair it with runtime gates: `fastloom.launcher.utils.is_installed("module_name")` or `isinstance(Configs.general, Capability)`. Don't put unguarded imports of optional packages at module top level — `import fastloom` must work with the minimum extras.

## Settings field naming

- **Capability fields** use SCREAMING_SNAKE_CASE (`MONGO_URI`, `RABBIT_URI`, `REDIS_URL`, `APP_PORT`). They double as env-var names — `fastloom.settings.utils.pydantic_env_or_default` reads from the environment when present.
- **Tenant-scoped, business-domain fields** use snake_case (`website_url`, `choice_sources`, `questions`).
- Prefer `Annotated[T, BeforeValidator(pydantic_env_or_default)]` for any field that should fall back to its env var (see `fastloom.observability.settings.EnvBackend`).

## Typing discipline

Pydantic-everywhere is load-bearing — the type system is a runtime invariant, not a hint.

- **Statically type every interface.** Reach for generics (`[T]`, `[T: BaseModel]`) when the shape is polymorphic — see `Configs[T, V]`, `PaginatedResponse[T]`, `SignalMessage[T]`, `Str[T]`.
- **No `Any`, no untyped `dict[str, Any]` as a data container.** Model the shape with pydantic and validate at the boundary.
- **Avoid `cast()` / `assert isinstance(...)` as a substitute for proper typing.** If mypy can't follow the flow, fix the surrounding shape rather than silence the checker. The one acceptable carve-out is `# type: ignore[misc]` on `Configs[X].general` lines (mypy can't follow PEP 695 generic + metaclass forwarding).
- **No `dict.get(...)` on a typed dict, no `getattr(obj, name)` on a typed object.** `.get` returning `None` masks bugs the type system would otherwise catch. If a key/attribute is optional, model it that way and let the type checker enforce the `None` branch.

When tempted to reach for `Any` / `dict.get` / `getattr` / `cast`, the upstream schema is almost always wrong — fix that instead.

## Validate at the pydantic boundary

When ingesting data (HTTP body, broker payload, YAML config, env var, file metadata), do validation, normalization, coercion, and alias resolution at the **schema** level. Don't write `if …:` checks after the data has already been parsed.

Reach for these before writing post-ingestion logic:

| Tool | For |
|------|-----|
| `BeforeValidator` | Transform raw input before pydantic's built-in coercion (strip whitespace, lowercase, parse a string into a list). |
| `AfterValidator` | Enforce invariants or transform after coercion (checksums, regex, custom rules). |
| `field_validator(mode="before"\|"after")` | Same idea, class-level — for multi-line logic that doesn't fit a one-liner `*Validator`. |
| `model_validator(mode="after")` | Cross-field invariants (e.g. "if `matched=True` then `path` and `content_type` must be set"). |
| `validation_alias` / `AliasChoices` | Accept different inbound keys (e.g. `tenant: str = Field(validation_alias="bucket")`). |
| `Field(default_factory=...)` | Runtime defaults — `utcnow`, UUID, env lookup. Never set defaults inside `__init__`. |
| Discriminated / left-to-right unions | Tagged shape resolution (`FileField = MatchedFile \| UnmatchedFile`). |
| `EmailStr`, `HttpUrl`, `AnyUrl`, `AmqpDsn`, `RedisDsn`, `Str[T]` | Pre-built validated types — use them, don't roll your own. |

If a handler / subscriber / repo function starts with `model_dump()` followed by `if …:` checks or key fix-ups, the logic belongs **upstream** in the schema. Push it.

Existing examples worth copying: `fastloom.types.NationalID` (`AfterValidator`), `fastloom.types.Str[T]` (`core_schema.no_info_after_validator_function`), `fastloom.file.schema.MediaPath` (`BeforeValidator`), `BaseFile.validate_content_length_and_matched` (`model_validator(mode="after")`), `FileMessage.tenant` (`validation_alias="bucket"`), `OtelConfig` (`BeforeValidator(pydantic_env_or_default)`).

## Defaults in exactly one place

A pydantic `Field` default is **the** source of truth. Don't restate it in `__init__`, in callers, in a `model_validator`, in YAML examples, or in docs. If you change the default, exactly one line changes.

## Privacy and dedupe

- **Default to public.** A new method is public unless it's a framework internal (FastStream lifecycle hook, Beanie event handler, sidecar wire-format detail). Justify the underscore; "I don't want callers to use this" is not a justification.
- **Dedupe aggressively.** Three repetitions of the same helper across files = lift to `utils.py` for that submodule, or to `fastloom.meta` / `fastloom.types` if it's generic. Frameworks tolerate duplication poorly — they're meant to be the dedup target.

## README and docs are part of the contract

When a change touches the **public surface** — new route, new settings field, extras-list change, renamed public symbol — update `README.md` and the relevant `docs/*.md` in the **same commit**. If a PR adds a new public symbol with no doc update, it isn't done. `README.md` is for users; `docs/` is for contributors onboarding; `.claude/CLAUDE.md` is for editors — different audiences, all required.

## Datetime hygiene

- Use `fastloom.date.utcnow()` (timezone-aware UTC). Never `datetime.utcnow()` (deprecated, naive).
- `fastloom.date.datetime_to_jalali`, `datetime_to_timestamp`, `get_zero_time` are available for common conversions.

## `Str[T]` validated string type

`fastloom.types.Str[HttpUrl]`, `Str[AmqpDsn]`, `Str[RedisDsn]` — string subclass that runs a pydantic adapter on validate and serializes as a plain `str`. Use it whenever you want pydantic to validate a URL/DSN but downstream code needs a plain string (e.g. uvicorn args, env-var exports).

## Lint / format

- `ruff` with line length **79**, double-quoted strings, magic trailing commas preserved.
- Enabled rule families: `E,W,F,C90,UP,B,SIM,INT,I,FAST`.
- `F401` is **never auto-fixed** (unused imports surface, but aren't deleted).
- `__init__.py` ignores `F` and `E402`; `tests/`, `docs/`, `tools/` ignore `E402`.

## Type checking

- `mypy` with `pydantic.mypy` and `returns.contrib.mypy.returns_plugin`.
- Pydantic `init_forbid_extra = true`, `init_typed = true`, `warn_required_dynamic_aliases = true`. New code must satisfy these.

## Pre-commit

Always before pushing:

```bash
poetry run pre-commit run --all-files --show-diff-on-failure
```

Hooks: ruff (check + format), mypy, basic file fixers, `poetry-check`, `poetry-lock`.

## Minimalism

No comments that re-state the code, no docstrings that paraphrase signatures, no "added for ticket #123" notes, no error handling for paths that can't happen, no feature flags for code that can just be changed. Trust internal callers; validate only at system boundaries (HTTP, broker, DB).
