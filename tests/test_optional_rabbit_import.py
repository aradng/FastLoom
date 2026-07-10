import importlib
import sys

import pytest

_AFFECTED_PREFIXES = (
    "aio_pika",
    "confluent_kafka",
    "faststream",
    "fastloom.signals",
    "fastloom.tenant.depends",
    "fastloom.tenant.settings",
    "fastloom.mcp.lifehooks",
    "fastloom.launcher",
)


def _drop_affected_modules():
    for name in list(sys.modules):
        if name.startswith(_AFFECTED_PREFIXES):
            del sys.modules[name]


def _blocked(*module_names):
    """`sys.modules[name] = None` fakes "not installed" for import/find_spec"""
    saved = {
        name: mod
        for name, mod in sys.modules.items()
        if name.startswith(_AFFECTED_PREFIXES)
    }
    _drop_affected_modules()
    for name in module_names:
        sys.modules[name] = None
    try:
        yield
    finally:
        _drop_affected_modules()
        sys.modules.update(saved)


@pytest.fixture
def without_aio_pika():
    yield from _blocked("aio_pika")


@pytest.fixture
def without_faststream():
    yield from _blocked("faststream")


@pytest.mark.parametrize(
    "module_name",
    [
        "fastloom.signals.depends",
        "fastloom.signals.middlewares",
        "fastloom.signals.healthcheck",
        "fastloom.db.signals",
        "fastloom.file.signals",
        "fastloom.tenant.settings",
        "fastloom.launcher.schemas",
        "fastloom.launcher.main",
    ],
)
def test_importable_without_rabbit_extra(without_aio_pika, module_name):
    """A Kafka-only (or Rabbit-absent) service must still import fine."""
    importlib.import_module(module_name)


@pytest.mark.parametrize(
    "module_name",
    [
        "fastloom.tenant.depends",
        "fastloom.tenant.settings",
        "fastloom.launcher.schemas",
        "fastloom.launcher.main",
    ],
)
def test_importable_without_any_broker(without_faststream, module_name):
    """A messaging-less service (no rabbit/kafka/redis) must still import."""
    importlib.import_module(module_name)
