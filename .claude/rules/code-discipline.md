---
description: Defaults discipline, private-by-justification, and README/docs as part of the contract
---

# Code discipline

## Defaults live in exactly one place

A pydantic `Field` default is **the** source of truth. Don't restate it:

- ❌ in `__init__` (`def __init__(self, x: int = 5)` while the field has `Field(default=5)`).
- ❌ in callers (`do_thing(x=5)` where 5 is already the field default).
- ❌ in a `model_validator` (`if self.x is None: self.x = 5`).
- ❌ in `tenants.example.yaml` (omit fields that have defaults; the YAML is a template for *non-default* values).
- ❌ in docs (let the field definition speak for itself).

If you change the default, you change one line.

## Privacy and dedupe

- **Default to public.** A new method on a class is public unless it's a framework internal (FastStream lifecycle hook, Beanie event handler, sidecar wire-format detail).
- **Justify the underscore.** `_foo` says "framework requires this name" or "this is a tightly coupled internal step." If it's just "I don't want callers to use this," that's not enough — write a comment or restructure.
- **Dedupe aggressively.** Three repetitions of the same helper across files = lift it to `utils.py` for that submodule, or to `fastloom.meta` / `fastloom.types` if it's generic. Frameworks tolerate duplication poorly because they're meant to be the dedup target.

## README and docs are part of the contract

When a change touches the **public surface** — a new route, a new env var / settings field, an extras-list change, a renamed public symbol, a flow change worth showing in the architecture diagram — update `README.md` and the relevant `docs/*.md` **in the same commit**.

- `README.md` — for users finding the project the first time. Keep it short, accurate, and don't let it drift.
- `docs/*.md` — the reference. `quickstart.md`, `launcher.md`, `tenant.md`, etc. are how a contributor onboards.
- `.claude/CLAUDE.md` and `.claude/rules/*.md` — for editors (you). Different audience, different scope.

If a PR adds a new public symbol with no doc update, it's not done.
