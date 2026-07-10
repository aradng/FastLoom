import importlib
import sys

import pytest

_AFFECTED_PREFIXES = (
    "aio_pika",
    "faststream",
    "fastloom.signals",
    "fastloom.tenant.depends",
    "fastloom.tenant.settings",
    "fastloom.mcp.lifehooks",
    "fastloom.launcher",
)


class _BlockAioPika:
    def find_spec(self, name, path=None, target=None):
        if name == "aio_pika" or name.startswith("aio_pika."):
            raise ImportError(f"simulated: {name} not installed")
        return None


def _drop_affected_modules():
    for name in list(sys.modules):
        if name.startswith(_AFFECTED_PREFIXES):
            del sys.modules[name]


@pytest.fixture
def without_aio_pika():
    saved = {
        name: mod
        for name, mod in sys.modules.items()
        if name.startswith(_AFFECTED_PREFIXES)
    }
    _drop_affected_modules()
    blocker = _BlockAioPika()
    sys.meta_path.insert(0, blocker)
    try:
        yield
    finally:
        sys.meta_path.remove(blocker)
        _drop_affected_modules()
        sys.modules.update(saved)


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
    """Services without the `rabbit` extra must still import the launcher."""
    importlib.import_module(module_name)
