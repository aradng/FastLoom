from collections.abc import MutableMapping
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel
from pytest_mock import MockerFixture

from fastloom.launcher.utils import get_settings_cls, get_tenant_cls


@pytest.fixture
def settings_mock[V: BaseModel, T: BaseModel](
    mocker: MockerFixture,
    service_settings: T,
    tenant_settings: MutableMapping[str, V],
) -> MagicMock:
    from fastloom.tenant.utils import dump_settings, load_settings

    yaml_text = dump_settings(
        service_settings=service_settings,
        tenant_settings=tenant_settings,
        yaml_mode=True,
    )

    def _load_settings(*args, **kwargs):
        kwargs["config_stream"] = yaml_text
        return load_settings(*args, **kwargs)

    return mocker.patch(
        "fastloom.tenant.settings.load_settings",
        side_effect=_load_settings,
    )


@pytest.fixture
def TC(settings_mock):
    from fastloom.tenant.settings import Configs

    Configs.self = None
    try:
        yield Configs(get_settings_cls(), get_tenant_cls())
    finally:
        Configs.self = None
