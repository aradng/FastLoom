# Launcher & App model

The launcher orchestrates service startup. It discovers `app.py` and `settings.py` from the current working directory at runtime, builds the `Configs` singleton, initializes the messaging broker, wires observability, and constructs the FastAPI instance.

**Symbols at a glance**

- `fastloom.launcher.main.app()` — FastAPI factory used by uvicorn (`--factory` mode).
- `fastloom.launcher.main.main()` — CLI entrypoint installed as `launch`; runs uvicorn against the factory.
- `fastloom.launcher.schemas.App` — declarative pydantic model your `app.py` exports.
- `fastloom.launcher.settings.LauncherSettings` — `APP_PORT`, `DEBUG`, `WORKERS`, `SETTINGS_PUBLIC`.
- `fastloom.launcher.utils.combine_lifespans` — compose multiple `Lifespan` context managers into one.
- `fastloom.launcher.utils.is_installed` — runtime check for optional dependencies.
- `fastloom.launcher.utils.reload_app` — touch the caller's source file to trigger uvicorn `--reload`.

## Discovery contract

The launcher imports two files dynamically from `cwd`:

```python
# settings.py — must expose `Settings`, optionally `TenantSettings`
class Settings(...): ...
class TenantSettings(...): ...  # optional


# app.py — must expose `app: App`
from fastloom.launcher.schemas import App
app = App(...)
```

If `TenantSettings` is not defined, the launcher uses an empty `pydantic.BaseModel`. The settings module is `lru_cache`d, so the import is cheap on repeated access.

## `App` fields

```python
App(
    routes: list[tuple[APIRouter, str, str]] = [],
    mounts: list[tuple[str, ASGIApp] | tuple[str, ASGIApp, str]] = [],
    models: list[type[Document | UnionDoc | View]] = [],
    models_module: ModuleType | None = None,
    signals_module: ModuleType | None = None,
    healthchecks: list[Callable[[], Awaitable[None]]] = [],
    additional_instruments: list[Callable] = [],
    lifespan_fn: Lifespan = default_lifespan(),
    exception_handlers: list[tuple[int | type[Exception], handler]] = [],
    otel_sampling: logfire.SamplingOptions | None = None,
    cache_healthcheck: bool = False,
)
```

- **`routes`** — each tuple is `(router, prefix, openapi_tag)`. The prefix is appended to `FastAPISettings.API_PREFIX` (default `/api/<PROJECT_NAME>`).
- **`mounts`** — sub-ASGI apps to mount. Tuple is `(path, app)` or `(path, app, name)`.
- **`models_module`** — a package whose submodules each contain `beanie.Document` / `View` / `UnionDoc` subclasses. The launcher walks it via `pkgutil.iter_modules` and registers everything for Beanie.
- **`models`** — explicit list; takes precedence over `models_module`.
- **`signals_module`** — a package whose subpackages each contain RabbitMQ subscribers. The launcher imports them so FastStream registers the handlers.
- **`healthchecks`** — extra async callables run by the `/healthcheck` endpoint. Library-provided checks (Mongo, Rabbit, Redis) are added automatically when the corresponding capability is configured.
- **`additional_instruments`** — extra OpenTelemetry instrumentation callables run inside `InitMonitoring`. Use this for service-specific instruments like `instrument_asyncpg`.
- **`lifespan_fn`** — your service's lifespan. The launcher composes it with the library's internal lifespan(s) via `combine_lifespans` (LIFO entry/exit).
- **`exception_handlers`** — list of `(exc_class_or_status_code, handler)` pairs. `CustomI18NException` is registered automatically.
- **`otel_sampling`** — override OTel sampling via `logfire.SamplingOptions` (e.g. parent-based with a custom sampler).
- **`cache_healthcheck`** — when `True`, adds a Redis healthcheck handler.

`App` is a pydantic model with `arbitrary_types_allowed=True`. Validators auto-fill `models` from `models_module` and assert that `signals_module` is only set when `Settings` inherits from `RabbitmqSettings`.

## Startup order (load-bearing)

`fastloom/launcher/main.py:48-105` runs these steps in this exact order:

1. Construct `Configs(Settings, TenantSettings)` and load `tenants.yaml`.
2. If `Settings` inherits `LoggingSettings`, call `setup_logging`.
3. If `Settings` inherits `RabbitmqSettings`, construct `RabbitSubscriber(...)` **before** monitoring — so aio-pika instrumentation can attach.
4. Compose lifespans: the library's `lifespan` (Beanie init + Redis migrator + signal stream registration) + optional `mcp_lifespan` + your `App.lifespan_fn`.
5. Enter `InitMonitoring(...)` context — configures Logfire, Sentry, OpenTelemetry. Auto-enables instrumentation for Redis/Rabbit/Mongo/Pydantic-AI via `infer_instruments`.
6. Build the FastAPI instance (custom `docs_url`, `openapi_url`, OAuth2 redirect under `API_PREFIX`).
7. Register CORS, exception handlers, healthcheck routes, system endpoints, then user routes, mounts, MCP mount, RabbitSubscriber router.
8. Call `monitor.instrument(app, …)` **last** — FastAPI instrumentation must run after all middlewares and routes are bound, or it will miss them.

Don't reorder these steps. If you need to inject behavior, hook into `App.lifespan_fn` or `App.additional_instruments`.

## `combine_lifespans`

Lifespans run in **insertion order on enter**, **reverse on exit** (LIFO), with their yielded dicts merged (later keys win on conflict).

```python
from fastloom.launcher.utils import combine_lifespans

app = FastAPI(lifespan=combine_lifespans(db_lifespan, mcp_lifespan, my_lifespan))
```

It accepts both FastAPI-style lifespans (yield `None`) and FastMCP-style (yield `dict`). This is what the launcher uses internally to merge the library's lifespan, the optional MCP lifespan, and your `App.lifespan_fn`.

## `LauncherSettings`

```python
class LauncherSettings(BaseModel):
    APP_PORT: int = 8000
    DEBUG: bool = True       # enables uvicorn --reload
    WORKERS: int = 4
    SETTINGS_PUBLIC: bool = False  # when True, mounts /tenant_* under API_PREFIX
```

When `SETTINGS_PUBLIC=True`, the tenant settings endpoints are also exposed under `API_PREFIX` (in addition to the always-mounted unprefixed system endpoints). Keep this off in production unless you front the service with an auth layer.

## `reload_app`

A helper used by the system `/reload` endpoint to trigger uvicorn `--reload` from inside a request handler. Walks the call stack to find the first frame outside the library, touches that file, and (when not in `DEBUG`) sends `SIGHUP` to the parent process.

## Related

- [Settings & Configs](settings.md)
- [Tenant](tenant.md)
- [Observability](observability.md)
