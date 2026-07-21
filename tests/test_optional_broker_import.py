import importlib
import sys

import pytest

_AFFECTED_PREFIXES = (
    "aio_pika",
    "confluent_kafka",
    "faststream",
    "fastloom.extras",
    "fastloom.signals",
    "fastloom.tenant.depends",
    "fastloom.tenant.settings",
    "fastloom.mcp.lifehooks",
    "fastloom.launcher",
)

_MODULES = (
    "fastloom.signals.rabbit.depends",
    "fastloom.signals.rabbit.middlewares",
    "fastloom.signals.rabbit.healthcheck",
    "fastloom.signals.kafka.depends",
    "fastloom.signals.kafka.healthcheck",
    "fastloom.db.signals",
    "fastloom.file.signals",
    "fastloom.tenant.depends",
    "fastloom.tenant.settings",
    "fastloom.launcher.schemas",
    "fastloom.launcher.main",
)

_MISSING = {
    "kafka-only": ("aio_pika",),
    "rabbit-only": ("confluent_kafka",),
    "no-broker": ("faststream",),
}


def _drop_affected_modules():
    for name in list(sys.modules):
        if name.startswith(_AFFECTED_PREFIXES):
            del sys.modules[name]


@pytest.fixture
def missing(request):
    """`sys.modules[name] = None` fakes "not installed" for import/find_spec"""
    saved = {
        name: mod
        for name, mod in sys.modules.items()
        if name.startswith(_AFFECTED_PREFIXES)
    }
    _drop_affected_modules()
    for name in request.param:
        sys.modules[name] = None
    try:
        yield
    finally:
        _drop_affected_modules()
        sys.modules.update(saved)


@pytest.mark.parametrize(
    "missing", _MISSING.values(), ids=_MISSING.keys(), indirect=True
)
@pytest.mark.parametrize("module_name", _MODULES)
def test_importable_when_broker_missing(missing, module_name):
    importlib.import_module(module_name)
