---
description: Ruff, mypy, pre-commit configuration and how to satisfy them
---

# Lint, type-check, pre-commit

Ground rules so CI passes on the first try.

## Ruff

- Line length is **79**, double-quoted strings, magic trailing commas preserved.
- Enabled rule families: `E, W, F, C90, UP, B, SIM, INT, I, FAST`.
- `F401` (unused import) is **never auto-fixed** — it shows up, you decide. Don't blindly delete; sometimes the import has side effects (signals, plugin registration). Confirm before removing.
- Per-file ignores:
  - `__init__.py` — ignores `F` and `E402` (re-exports and conditional imports allowed).
  - `tests/`, `docs/`, `tools/` — ignore `E402`.
- Notebooks (`*.ipynb`) are excluded from `lint`.
- Run: `poetry run ruff check .` and `poetry run ruff format .`.

## mypy

- Plugins: `pydantic.mypy`, `returns.contrib.mypy.returns_plugin`.
- Pydantic config:
  - `init_forbid_extra = true` — extra kwargs to model `__init__` are an error.
  - `init_typed = false` — `__init__`'s synthesized signature doesn't require the field's exact declared type. Turned off because custom validator types (`Str[T]`, `HostPort`, `KafkaBootstrapServers`) accept a wider *input* type (e.g. plain `str`) than their declared field type, and `init_typed = true` doesn't distinguish that from a real mismatch.
  - `warn_required_dynamic_aliases = true`.
  - `RootModel` subclasses aren't fully covered by this setting either way — construct via `.model_validate(v)` instead of `Cls(v)` when `v` isn't already the declared root shape (see `fastloom.types.HostPort`).
- Run: `poetry run mypy fastloom`.

## Pre-commit

Always before pushing:

```bash
poetry run pre-commit run --all-files --show-diff-on-failure
```

Hooks (in `.pre-commit-config.yaml`):

1. `trailing-whitespace`, `end-of-file-fixer`, `check-yaml`, `check-added-large-files`.
2. `mypy` — with bundled `mypy-extensions`, `typing-extensions`, `pydantic`, `returns`, `types-pyyaml`.
3. `ruff` (check, `--fix`) and `ruff-format`.
4. `poetry-check`, `poetry-lock` — runs on `pyproject.toml` changes.

If a hook fails: fix the underlying issue, re-stage, and create a **new** commit. Don't `--amend` (the failed commit didn't happen; `--amend` would modify the previous one).

## Common fixes

- `E501` (line too long): break at function args, use parenthesized concatenation, or hoist a local.
- `F401` (unused import): if it's a re-export, add it to `__all__` in `__init__.py`; otherwise delete.
- `B008` (function call in default arg): use `Field(default_factory=...)` for pydantic, `lambda` for callables.
- `UP*` (pyupgrade): apply `--fix`; don't manually edit if `ruff --fix` will do it.
- `SIM*` (flake8-simplify): often legitimate; review the suggestion before silencing.
- mypy `[misc]` on `Configs[X].general`: the library uses `# type: ignore[misc]` on these lines — acceptable, mypy can't follow PEP 695 generic + metaclass forwarding here.

## Hooks: never skip

Don't use `--no-verify`, `--no-gpg-sign`, or any other bypass. If a hook fails, fix the underlying issue.
