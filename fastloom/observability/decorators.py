import inspect
from collections.abc import Callable
from functools import wraps

_CACHE: dict[str, tuple] = {}


def _metric_name(func: Callable) -> str:
    name = getattr(func, "__name__", "unknown")
    parts = (getattr(func, "__module__", None) or "").split(".")
    return f"{parts[1]}_{name}" if len(parts) > 1 else name


def prom_track(name: str | None = None):
    from prometheus_client import Counter, Histogram

    def decorator(func: Callable) -> Callable:
        base = name or _metric_name(func)
        counter, histogram = _CACHE.setdefault(
            base,
            (
                Counter(f"{base}_calls_total", f"Total calls of {base}"),
                Histogram(
                    f"{base}_duration_seconds",
                    f"Duration of {base} in seconds",
                ),
            ),
        )

        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def wrapper(*args, **kwargs):  # pyright: ignore[reportRedeclaration]
                counter.inc()
                with histogram.time():
                    return await func(*args, **kwargs)
        else:

            @wraps(func)
            def wrapper(*args, **kwargs):
                counter.inc()
                with histogram.time():
                    return func(*args, **kwargs)

        return wrapper

    return decorator
