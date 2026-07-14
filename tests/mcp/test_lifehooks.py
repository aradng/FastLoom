from unittest.mock import patch

import pytest

from fastloom.cache.lifehooks import RedisHandler
from fastloom.cache.settings import RedisSettings
from fastloom.mcp.lifehooks import _mcp_session_state_store, get_mcp
from fastloom.mcp.settings import MCPSettings
from fastloom.tenant.settings import Configs


def _bind_configs(**overrides):
    configs = Configs.__new__(Configs)
    configs.general = MCPSettings(PROJECT_NAME="test_service", **overrides)
    Configs.bind(configs)


@pytest.fixture(autouse=True)
def _clean_singletons():
    RedisHandler.unbind()
    Configs.unbind()
    yield
    RedisHandler.unbind()
    Configs.unbind()


def test_none_when_redis_handler_unbound():
    _bind_configs()
    assert _mcp_session_state_store() is None


def test_none_when_redis_handler_disabled():
    _bind_configs()
    RedisHandler(RedisSettings(REDIS_URL="redis://localhost:1/0"))
    assert _mcp_session_state_store() is None


def test_none_when_setting_disabled():
    _bind_configs(MCP_SESSION_STORE_ENABLED=False)
    RedisHandler(RedisSettings())
    assert _mcp_session_state_store() is None


def test_none_without_aredis_om_installed():
    _bind_configs()
    RedisHandler(RedisSettings())
    with patch("fastloom.mcp.lifehooks.AREDIS_OM_INSTALLED", False):
        assert _mcp_session_state_store() is None


def test_returns_redis_store_when_enabled(redis_container):
    from key_value.aio.stores.redis import RedisStore

    _, host, port = redis_container
    _bind_configs()
    RedisHandler(RedisSettings(REDIS_URL=f"redis://{host}:{port}/0"))

    store = _mcp_session_state_store()

    assert isinstance(store, RedisStore)


def test_get_mcp_wires_redis_backed_state_store(redis_container):
    from key_value.aio.stores.redis import RedisStore

    _, host, port = redis_container
    _bind_configs()
    RedisHandler(RedisSettings(REDIS_URL=f"redis://{host}:{port}/0"))
    get_mcp.cache_clear()

    try:
        mcp = get_mcp()
        assert isinstance(mcp._state_storage, RedisStore)
    finally:
        get_mcp.cache_clear()


def test_get_mcp_falls_back_to_memory_store_without_redis():
    from key_value.aio.stores.memory import MemoryStore

    _bind_configs()
    get_mcp.cache_clear()

    try:
        mcp = get_mcp()
        assert isinstance(mcp._state_storage, MemoryStore)
    finally:
        get_mcp.cache_clear()
