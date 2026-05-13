---
description: Reach for pydantic validators (BeforeValidator, AfterValidator, model_validator, validation_alias, AliasChoices, etc.) before writing post-ingestion business logic
paths: ["**/*.py"]
---

# Validate at the pydantic boundary, not after

When ingesting data (HTTP body, broker payload, YAML config, env var, file metadata), do validation, normalization, coercion, and alias resolution at the **schema** level. Don't write `if …:` checks after the data has already been parsed — that's logic in the wrong layer.

## Reach for these first

| Tool | Use it for |
|------|-----------|
| `BeforeValidator` | Transform raw input *before* pydantic's built-in coercion (strip whitespace, lowercase, parse a string into a list, accept multiple representations). |
| `AfterValidator` | Enforce invariants or transform *after* coercion (checksum check, regex, custom rule). |
| `field_validator(mode="before"\|"after")` | Same idea, class-level. Reach for it when the logic is too multi-line for a one-liner `BeforeValidator`. |
| `model_validator(mode="after")` | Cross-field invariants (e.g. "if A is set then B and C must also be set"). |
| `validation_alias` | Accept a wire-side key different from the field name (e.g. `tenant: str = Field(validation_alias="bucket")`). |
| `AliasChoices` | Accept several inbound keys for the same field. |
| `Field(default_factory=...)` | Runtime defaults — `utcnow`, UUID, env lookup. Never set defaults in `__init__`. |
| Discriminated unions / left-to-right unions | Tagged shape resolution (e.g. `FileField = MatchedFile \| UnmatchedFile`). |
| `EmailStr`, `HttpUrl`, `AnyUrl`, `PostgresDsn`, `AmqpDsn`, `RedisDsn`, `Str[T]` | Pre-built validated types. Use them; don't roll your own. |

## Anti-patterns

- ❌ A route handler that parses a comma-separated string into a list — use `BeforeValidator`.
- ❌ `if not "@" in user.email:` checks downstream of pydantic — use `EmailStr` or `AfterValidator`.
- ❌ Mutating fields inside `__init__` to fill defaults — use `Field(default=...)` / `Field(default_factory=...)`.
- ❌ Renaming inbound JSON keys inside the handler (`payload["bucket"] = payload.pop("tenant")`) — use `validation_alias` / `AliasChoices`.
- ❌ A subscriber / repo function that starts with `model.model_dump()` then patches keys before re-validating — push the patches into the schema.
- ❌ Manual conversion between two shapes via `dict(...)` then `model_validate(...)` — use a `model_validator(mode="before")` or a `BeforeValidator` on the target field.

## Existing references in the codebase

- `fastloom.types.NationalID` — `AfterValidator(_national_id_validator)` for the Iranian national-ID checksum.
- `fastloom.types.Str[T]` — `core_schema.no_info_after_validator_function` to validate URLs/DSNs as plain `str` subtypes.
- `fastloom.file.schema.MediaPath` — `BeforeValidator(_file_to_path)` coerces `str` / `dict` / `Path` / file-like objects into a normalized path.
- `fastloom.file.schema.BaseFile.validate_content_length_and_matched` — `model_validator(mode="after")` enforces the four-way `matched` invariant.
- `fastloom.file.schema.FileMessage.tenant` — `Field(validation_alias="bucket")` accepts `bucket` from the wire as `tenant`.
- `fastloom.observability.settings.OtelConfig` — `BeforeValidator(pydantic_env_or_default)` for env-var fallbacks.
- `fastloom.db.schemas.BasePaginationQuery.convert_zero_limit` — `field_validator(mode="after")` normalizes `limit=0` to `None`.

## Rule of thumb

If your handler / subscriber / repo function starts with a `model_dump()` followed by `if …:` checks or key fix-ups, the logic belongs **upstream** in the schema. Push it.
