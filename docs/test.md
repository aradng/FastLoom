# Testing

Fastloom ships with a batteries-included test helper package: pytest fixtures that build an isolated `TestClient`, swap settings between cases, mock auth, spin up real-service docker containers via `testcontainers`, and a diff-friendly assertion helper for response comparison.

**Symbols at a glance**

- `fastloom.test.fixtures.app.init_app` — pytest fixture producing a `TestClient` bound to the service factory with a host header for tenant routing.
- `fastloom.test.fixtures.auth.*` — `user_claims`, `admin_claims`, `user_token`, `admin_token`, `admin_token_headers`, etc., plus an `autouse` `mock_authz` that stubs the IAM sidecar.
- `fastloom.test.fixtures.settings.settings_mock`, `TC` — rebuild the `Configs` singleton from in-test YAML.
- `fastloom.test.fixtures.docker.mongo_container` — session-scoped Mongo via testcontainers.
- `fastloom.test.fixtures.docker.kafka_container` — session-scoped Kafka (KRaft mode, no Zookeeper) via testcontainers.
- `fastloom.test.fixtures.docker.redis_container` — session-scoped Redis via testcontainers (`redis-stack-server` image, so RediSearch is available for `redis-om` indexes).
- `fastloom.test.fixtures.docker.postgres_container` — session-scoped Postgres via testcontainers (not used by fastloom itself — for services that bring their own Postgres/SQLAlchemy layer).
- `fastloom.test.fixtures.shared` — opt-in pytest plugin: one Postgres and/or Mongo for the whole run, shared by every xdist worker, with a database per worker (`shared_postgres`, `shared_mongo`, `worker_database`).
- `fastloom.test.container.create_container`, `PrivateRegistryDocker` — testcontainers helper with private-registry auth.
- `fastloom.test.utils.assert_deep_diff`, `status_check`, `assert_success`, `expect_calling`, `to_dict`, `generate_token`, `token_to_header`, `ignore_keys` — assertion + setup helpers.
- `fastloom.test.constants` — `SECRET_KEY`, image names, port constants.

## Install

```bash
uv add --group test "fastloom[test]"
```

The `test` extra pulls in `pytest`, `pytest-asyncio`, `pytest-mock`, `pytest-cov`, `pytest-xdist`, `pytest-lazy-fixtures`, `testcontainers`, `deepdiff`, `freezegun`.

## Layout

Put a `conftest.py` at the test root that re-exports the fastloom fixtures and supplies the project-specific ones:

```python
# tests/conftest.py
from fastloom.test.fixtures.app import init_app          # noqa: F401
from fastloom.test.fixtures.auth import *                # noqa: F401, F403
from fastloom.test.fixtures.settings import settings_mock, TC  # noqa: F401
from fastloom.test.fixtures.docker import mongo_container      # noqa: F401

import pytest

from settings import Settings, TenantSettings


@pytest.fixture
def service_settings(mongo_container) -> Settings:
    container, host, port = mongo_container
    return Settings(
        ENVIRONMENT="test",
        PROJECT_NAME="my_service",
        MONGO_URI=f"mongodb://{host}:{port}",
        MONGO_DATABASE="test",
        # ... other capability fields
    )


@pytest.fixture
def tenant_settings(tenant_name: str) -> dict[str, TenantSettings]:
    return {tenant_name: TenantSettings(name=tenant_name)}
```

The fastloom fixtures expect you to provide:

- `service_settings: Settings` — the fully populated service-wide settings instance.
- `tenant_settings: dict[str, TenantSettings]` — tenants to register.

Everything else (the YAML stub, the singleton wiring, the `TestClient`, the JWT generation, the auth mocks) is supplied by the library fixtures.

## The `TC` fixture — reset between tests

```python
# fastloom/test/fixtures/settings.py
@pytest.fixture
def TC(settings_mock):
    from fastloom.tenant.settings import Configs

    Configs.self = None
    try:
        yield Configs(get_settings_cls(), get_tenant_cls())
    finally:
        Configs.self = None
```

The fixture nukes the class-level singleton, builds a fresh one from your stub `service_settings` + `tenant_settings`, hands it to the test, and clears it again. This is the only place outside the launcher that's allowed to mess with `Configs.self`.

## `patch_tenant_loader_at_import` — eager `TC` binding

Only relevant if your `settings.py` binds `TC` eagerly (`TC = Configs(service_cls=Settings, tenant_cls=TenantSettings)`) instead of the default class-alias form — see [Conventions](conventions.md#eager-vs-deferred-tcgeneral-reads) for why a service would do that.

```python
# tests/conftest.py
from fastloom.test.fixtures.settings import patch_tenant_loader_at_import

from settings import Settings, TenantSettings

patch_tenant_loader_at_import(
    Settings(ENVIRONMENT="test", PROJECT_NAME="my_service", ...),
    {"acme": TenantSettings(name="acme")},
)

from fastloom.test.fixtures.app import *  # noqa: E402, F403
from fastloom.test.fixtures.auth import *  # noqa: E402, F403
```

Call it as a bare statement at conftest.py **module scope** — never inside a fixture, autouse or otherwise, and before any local import that could pull in `settings.py`. pytest imports conftest.py before collecting sibling test files in that directory; that's the only point early enough to beat an eager `TC = Configs(...)` binding, which fires the moment anything first imports `settings.py`. A fixture only runs at test-execution time, after the entire collection phase — by then a test file's own top-level import (`from myservice.constants import Topic`, say) may already have triggered `settings.py`'s construction against the real loader, silently defeating the point of patching at all.

## `init_app` — TestClient with tenant routing

```python
@pytest_asyncio.fixture
def init_app(tenant_name: str, TC) -> TestClient:
    return TestClient(
        app=app(),
        base_url=f"http://testserver{TC.general.API_PREFIX}",
        headers={
            "x-forwarded-host": f"{tenant_name}.com",
            "accept-language": "en",
        },
    )
```

The host header drives `HeaderSource` to resolve the test tenant. The `accept-language` header pins translations to English so assertions on `message_tr` are stable.

```python
def test_ping(init_app, admin_token_headers):
    r = init_app.get("/ping", headers=admin_token_headers)
    assert_success(r)
    assert_deep_diff(r.json(), {"pong": "ok"})
```

## Auth: mocked sidecar, real JWT

The `mock_authz` fixture is `autouse` — it patches `OptionalJWTAuth._acl` and `OptionalJWTAuth._introspect` to return `None`, so every test runs in `INTROSPECT=False` / `ACL=False` mode regardless of `Settings` config. The JWT signature is still validated locally via `jose` against `SECRET_KEY = "test_secret"`.

Token fixtures:

| Fixture | Returns |
|---------|---------|
| `user_claims` | `UserClaims` for a regular user (random UUID, generated email). |
| `admin_claims` | `UserClaims` with `roles=[ADMIN_ROLE]`. |
| `user_token` / `admin_token` | Signed JWT string. |
| `user_token_headers` / `admin_token_headers` | `{"Authorization": "Bearer ..."}` dict. |

Override `user_claims` in your `conftest.py` if you need specific roles/scopes/orgs for a test.

## `assert_deep_diff` — the response assertion you actually want

```python
from fastloom.test.utils import assert_deep_diff

assert_deep_diff(
    r.json(),
    {
        "id": ...,                    # ignore — use ellipsis as a wildcard
        "name": "Alice",
        "tags": [{"id": ..., "label": "x"}, {"id": ..., "label": "y"}],
    },
)
```

Behavior:

- Wraps `deepdiff.DeepDiff` with `ignore_order=True`, `verbose_level=2`, sane type-group config.
- **`...` (Ellipsis) is a wildcard.** Useful for ignoring server-generated ids, timestamps, anything you don't want to assert on.
- Knows `bson.ObjectId` / `PydanticObjectId` / `str` are equivalent.
- For lists: pass `key="id"` to sort + zip by that key before diffing. Add `use_compare_func=True` to use `deepdiff`'s iterable compare function instead.
- Pretty-prints the diff via `diff.to_json(...)` on failure — no more squinting at single-line dict reprs.

Companion helpers:

```python
status_check(r, 422)            # asserts r.status_code == 422 with full response text on fail
assert_success(r)               # r.is_success
assert_no_data(r)               # 200 + {"count": 0, "data": []}
ignore_keys(d, "items.0.id")    # mutate d so deepdiff ignores that path
to_dict(model)                  # model.model_dump_json -> dict (preserves JSON-mode coercions)
expect_calling(mock, [...], key="id")  # assert async mock was called with a sequence of payloads
```

## Docker-backed integration tests

```python
@pytest.fixture(scope="session")
def mongo_container() -> ContainerDataFixture:
    with create_container(MONGO_IMAGE, port=MONGO_PORT) as (container, port_str):
        yield container, LOCALHOST_BASE_URL, port_str
```

`create_container` is a thin context manager over `testcontainers.core.container.DockerContainer` with three extras:

1. Logs in to a **private registry** only when `REGISTRY_ADDRESS` is set (with `REGISTRY_USERNAME`, `REGISTRY_PASSWORD`). Without it there's no login round trip, which used to cost ~1.7s per container.
2. Accepts `env_vars`, `volumes`, `commands`, `tmpfs`, `wait_strategy` as plain kwargs.
3. Yields `(container, host, exposed_port_string)`.

`redis_container` and `postgres_container` are already provided the same way — import them instead of rolling your own:

```python
from fastloom.test.fixtures.docker import postgres_container, redis_container  # noqa: F401


@pytest.fixture
def service_settings(redis_container) -> Settings:
    container, host, port = redis_container
    return Settings(
        ENVIRONMENT="test",
        PROJECT_NAME="my_service",
        REDIS_URL=f"redis://{host}:{port}/0",
        # ... other capability fields
    )
```

`postgres_container` is tuned for tests: data on tmpfs, `trust` auth (asyncpg's SCRAM handshake is pure Python, ~8ms CPU per connect), `fsync`/`synchronous_commit`/`full_page_writes` off, `max_connections=500`, and readiness probed over TCP every 100ms (the image's init-time server listens on the unix socket only, so a socket probe can pass too early).

`redis_container` uses the `redis-stack-server` image, not plain `redis` — `redis-om`'s indexed `JsonModel` queries need the RediSearch module, which the stock image doesn't ship. `postgres_container` isn't consumed by anything in fastloom itself (fastloom has no Postgres capability); it's there for services that bring their own Postgres/SQLAlchemy layer, matching the same `(container, host, port)` shape as every other fixture here.

Need a broker container fastloom doesn't ship (e.g. RabbitMQ)? Spin it up the same way `create_container` is used above — same three kwargs, same yielded shape — and wire the resulting URI into `service_settings`.

Kafka doesn't fit `create_container`'s single-port model (KRaft/Zookeeper listener config, advertised listeners) — use the fastloom-provided `kafka_container` fixture instead, which wraps `testcontainers.kafka.KafkaContainer` directly:

```python
from fastloom.test.fixtures.docker import kafka_container  # noqa: F401


@pytest.fixture
def service_settings(kafka_container) -> Settings:
    return Settings(
        ENVIRONMENT="test",
        PROJECT_NAME="my_service",
        KAFKA_URI=kafka_container.get_bootstrap_server(),
        # ... other capability fields
    )
```

## One shared container for the whole run

Each xdist worker is its own process, so a session-scoped `postgres_container` starts one Postgres **per worker**: `-n 8` means 8 boots, 8 sets of migrations, 8 data directories competing for disk. Load the `fastloom.test.fixtures.shared` plugin instead and the controller starts one container before the workers spawn, hands its address to each worker through xdist's `workerinput`, and stops it at the end. Each worker gets its own database, so tests stay isolated.

```toml
# pyproject.toml
[tool.pytest.ini_options]
addopts = "-n 8 -p fastloom.test.fixtures.shared"
fastloom_shared_containers = ["postgres"]   # and/or "mongo"
fastloom_postgres_image = "postgres:18"     # default: fastloom.test.constants.POSTGRES_IMAGE
```

```python
# tests/conftest.py
@pytest.fixture(scope="session")
def service_settings(shared_postgres, worker_database) -> Settings:
    return Settings(
        POSTGRES_DSN=(
            f"postgresql+asyncpg://postgres@{shared_postgres.host}:"
            f"{shared_postgres.port}/{worker_database}"
        ),
        # ...
    )
```

- `shared_postgres` creates `worker_database` (`test_gw0`, `test_gw1`, …; `test_master` at `-n 0`) with `createdb` inside the container, so the service needs no Postgres driver of its own to set it up. Run your migrations against it in a session fixture.
- `shared_mongo` needs no setup: use `worker_database` as the Mongo database name. It's a standalone `mongod`, so code that needs a replica set (transactions, change streams) still needs its own container.
- Works at `-n 0` too (the single process owns the container). Requires xdist's `worker_id` fixture, which the `test` extra installs.
- `--collect-only` and `--fixtures` don't start anything.
- Use a database, not a schema, per worker: anything set with `ALTER DATABASE … SET` stays private to its worker.
- Redis isn't in the list: RediSearch refuses `FT.CREATE` on any db but 0, so redis-om indexes can't share one server. Keep `redis_container` per worker.

## Running

```bash
# Full suite
uv run pytest

# Single test
uv run pytest tests/api/test_users.py::test_create_user

# Parallel (xdist) — testcontainers fixtures must be session-scoped
uv run pytest -n auto

# With coverage
uv run pytest --cov=my_service --cov-report=term-missing

# Verbose, no capture
uv run pytest -vv -s

# Time-freeze a test
@freezegun.freeze_time("2024-01-01")
def test_clock(...): ...
```

## Patterns

### Snapshotting a list response

```python
def test_list(init_app, admin_token_headers, prepopulated_items):
    r = init_app.get("/items", headers=admin_token_headers)
    assert_success(r)
    assert_deep_diff(
        r.json(),
        {
            "count": 3,
            "data": [
                {"id": ..., "name": "a", "created_at": ...},
                {"id": ..., "name": "b", "created_at": ...},
                {"id": ..., "name": "c", "created_at": ...},
            ],
        },
        key="name",  # sort lists by `name` before diffing
    )
```

### Asserting a signal was published

```python
from unittest.mock import AsyncMock

def test_publishes(init_app, mocker, admin_token_headers):
    pub = mocker.patch(
        "fastloom.signals.rabbit.depends.RabbitSubscriber.publisher",
        return_value=AsyncMock(),
    )
    init_app.post("/orders", json={...}, headers=admin_token_headers)
    expect_calling(
        pub.return_value.publish,
        [{"item": "...", "quantity": 1}],
        key="item",
    )
```

### Testing per-tenant resolution

```python
@pytest.mark.asyncio
async def test_tenant_override(TC, tenant_name):
    cfg = await TC[tenant_name]
    assert cfg.name == tenant_name
    cfg.website_url = "https://example.test"
    await TC.set(tenant_name, cfg)
    refetched = await TC[tenant_name]
    assert refetched.website_url == "https://example.test"
```

## Related

- [Conventions](conventions.md) — `SelfSustaining` is what makes the singleton reset trick possible.
- [Auth](auth.md) — what `mock_authz` is stubbing out.
- [Settings](settings.md) — the `Settings` / `TenantSettings` shape the fixtures expect.
