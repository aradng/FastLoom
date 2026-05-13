---
description: Strict static typing — no Any, no untyped dicts, no dict.get / getattr on typed shapes
paths: ["**/*.py"]
---

# Typing

Pydantic-everywhere is load-bearing. The type system is a runtime invariant, not a hint.

## Rules

1. **Statically type every interface.** Function signatures, class attributes, return values. If a callable is polymorphic, reach for generics (`[T]`, `[T: BaseModel]`) — see `Configs[T, V]`, `PaginatedResponse[T]`, `SignalMessage[T]`, `Str[T]`.

2. **No `Any`.** If you're tempted, the wrong abstraction is hiding upstream. `dict[str, Any]` is a code smell: model the shape with pydantic and validate at the boundary.

3. **No untyped dicts as data containers.** Use a pydantic model. The runtime cost is negligible; the readability and editor-completion win is large.

4. **Avoid explicit casts.** `cast(X, value)` and `assert isinstance(value, X)` to satisfy mypy bypass the actual safety net. If mypy can't follow the flow, the surrounding code shape is wrong — refactor rather than silence. The two legitimate cast locations:
   - `# type: ignore[misc]` on `Configs[X].general` lines — mypy can't follow PEP 695 generic + metaclass forwarding. Acceptable.
   - Boundaries with external libraries that aren't typed.

5. **No `dict.get(...)` on a typed dict.** `.get` returning `None` masks bugs that the type system would otherwise catch. If a key is optional, the schema should say so; then access it as `model.field` and mypy enforces the `None` handling.

6. **No `getattr(obj, name)` on a typed object.** Same reason. If you need dynamic attribute access, the surface is wrong — usually a pydantic model with a discriminator is what you want.

## Pydantic v2 specifics

- `Field(default=..., default_factory=...)`, not `__init__` defaults.
- `model_validator(mode="after")` for cross-field invariants; not in `__init__`.
- `model_dump(by_alias=True)` when serializing for the wire if the schema has aliases.
- Use `model_validate(...)` and `model_dump(...)` — never `.dict()` / `.parse_obj(...)` (v1 API).

## When in doubt

If you're reaching for `Any` / `dict.get` / `getattr` / `cast`, **stop and fix the schema instead.** It almost always reveals a missing pydantic model or an under-typed function signature.
