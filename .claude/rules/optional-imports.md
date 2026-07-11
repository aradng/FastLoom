---
description: Optional-dependency import idiom for extras (mongo, rabbit, redis, mcp, ...)
paths: ["**/*.py"]
---

# Optional-dependency imports

Fastloom ships many optional extras (`mongo`, `rabbit`, `kafka`, `redis`, `mcp`, `openai`, `celery`). Any module that imports from one of those extras must degrade gracefully when the extra is absent — `import fastloom` must work with the minimum install.

## The exact pattern

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

The pattern is **load-bearing in this exact shape**:

- `TYPE_CHECKING` branch gives mypy / IDE the real type — autocomplete, type narrowing, error checking all work.
- `try/except ImportError` runtime branch swaps in `pydantic.BaseModel` (or another no-op stand-in) so import never fails.
- Subclassing `Document` at runtime against the fallback `BaseModel` works because both expose pydantic-compatible APIs for the fields we use.

For non-class imports (functions, decorators), provide a no-op fallback that preserves the signature:

```python
if TYPE_CHECKING:
    from beanie import before_event
else:
    try:
        from beanie import before_event
    except ImportError:
        def before_event(*args, **kwargs):
            def decorator(func):
                return func
            return decorator
```

## Runtime gating

Pair the import pattern with a runtime gate. Two correct forms:

```python
from fastloom.extras import AIO_PIKA_INSTALLED

if AIO_PIKA_INSTALLED:
    ...
```

```python
if isinstance(TC.general, RabbitmqSettings):
    ...
```

`isinstance(TC.general, X)` is preferred when the capability is driven by which settings mixin the service inherited.

`fastloom.extras` is the single place every optional module's installed-flag is computed (once, at import time, via `fastloom.launcher.utils.is_installed`) — import the precomputed `X_INSTALLED` constant from there rather than calling `is_installed("module_name")` yourself at each call site. Add a new one there when wiring a new optional integration.

Test note: `tests/test_optional_broker_import.py` simulates "package missing" by setting `sys.modules[name] = None` and force-reimporting a fixed module list — any module whose top-level code caches an `is_installed()` result (like `fastloom.extras`) must be in that test's `_AFFECTED_PREFIXES` reload list, or the cached value goes stale across parametrized runs.

## Anti-patterns

- ❌ Unguarded top-level imports of `beanie`, `aio_pika`, `aredis_om`, `fastmcp`, `openai`. They break the minimum install.
- ❌ Importing inside function bodies as a substitute for the pattern — slower, scattered, hides the optional dependency from readers.
- ❌ Wrapping the `try/except` in `TYPE_CHECKING` (instead of `else`). Type checker then never sees the symbol.
- ❌ Catching anything other than `ImportError`. We're guarding the missing-package case, not silencing real bugs.
