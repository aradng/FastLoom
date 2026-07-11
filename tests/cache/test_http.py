from unittest.mock import MagicMock

from fastapi import FastAPI
from pydantic import BaseModel
from redis_fastapi import get_settings
from redis_fastapi.cache import (
    CacheHitException,
    CacheResponseCaptureMiddleware,
)

import fastloom.cache.http as http
from fastloom.cache.http import scoped_eviction_group, setup_http_cache
from fastloom.cache.settings import RedisSettings
from fastloom.tenant import Tenant


class _NotRedisSettings(BaseModel):
    pass


def test_scoped_eviction_group_folds_in_tenant_when_set():
    assert scoped_eviction_group("products") == "products"

    token = Tenant.set("acme")
    try:
        assert scoped_eviction_group("products") == "acme:products"
        assert scoped_eviction_group() == "acme"
    finally:
        Tenant.reset(token)


def test_setup_http_cache_noop_for_non_redis_settings():
    app = FastAPI()
    setup_http_cache(app, _NotRedisSettings())
    assert not any(
        m.cls is CacheResponseCaptureMiddleware for m in app.user_middleware
    )


def test_setup_http_cache_wires_middleware_pool_url_and_project_prefix(
    monkeypatch,
):
    configs = MagicMock()
    configs.__getitem__.return_value.general.PROJECT_NAME = "my_service"
    monkeypatch.setattr(http, "Configs", configs)

    app = FastAPI()
    settings = RedisSettings(REDIS_URL="redis://cache-host:6379/2")
    setup_http_cache(app, settings)

    assert any(
        m.cls is CacheResponseCaptureMiddleware for m in app.user_middleware
    )
    assert app.exception_handlers.get(CacheHitException) is not None
    assert get_settings().url == "redis://cache-host:6379/2"
    assert get_settings().prefix == "my_service"
