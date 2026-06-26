from collections.abc import Generator, MutableMapping
from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from fastloom.launcher.utils import get_settings_cls, get_tenant_cls

if TYPE_CHECKING:
    from fastloom.tenant.settings import Configs


@contextmanager
def patched_settings[V: BaseModel, T: BaseModel](
    service_settings: T,
    tenant_settings: MutableMapping[str, V] | None = None,
) -> Generator[None]:
    from fastloom.tenant.utils import dump_settings, load_settings

    yaml_text = dump_settings(
        service_settings=service_settings,
        tenant_settings=tenant_settings if tenant_settings is not None else {},
        yaml_mode=True,
    )

    def _load_settings(*args, **kwargs):
        kwargs["config_stream"] = yaml_text
        return load_settings(*args, **kwargs)

    patcher = patch(
        "fastloom.tenant.settings.load_settings",
        side_effect=_load_settings,
    )
    patcher.start()
    try:
        yield
    finally:
        patcher.stop()


@contextmanager
def tc_context[V: BaseModel, T: BaseModel](
    service_settings: T,
    tenant_settings: MutableMapping[str, V] | None = None,
) -> "Generator[Configs[BaseModel, BaseModel]]":
    from fastloom.tenant.settings import Configs

    with patched_settings(service_settings, tenant_settings):
        Configs.self = None  # type: ignore[misc, assignment]
        try:
            yield Configs(get_settings_cls(), get_tenant_cls())
        finally:
            Configs.self = None  # type: ignore[misc, assignment]


@pytest.fixture
def settings_mock(service_settings, tenant_settings):
    with patched_settings(service_settings, tenant_settings):
        yield


@pytest.fixture
def TC(service_settings, tenant_settings):
    with tc_context(service_settings, tenant_settings) as configs:
        yield configs
