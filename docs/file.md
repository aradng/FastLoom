# File storage

Helpers and schemas for working with file objects and references.

- `core_bluprint.file.schema` — strict Pydantic models for file inputs/outputs
  - `FileField`, `OptionalFileField`, `MatchedFile`, `UnmatchedFile`
  - path coercion with `BeforeValidator` and `PlainSerializer`
- `core_bluprint.file.models` — Beanie `FileObject` and `FileReference` with indices

These schemas enforce invariants like: if `matched` is true, `path` and `content_type` must exist.
