import pkgutil
from importlib import import_module
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from beanie import Document

    from fastloom.db.signals import (
        Operations,
        SignalsSave,
        SignalsUpdate,
    )
else:
    try:
        from fastloom.db.signals import (
            Operations,
            SignalsSave,
            SignalsUpdate,
        )
    except ImportError:
        from types import NoneType as Operations
        from types import NoneType as SignalsSave
        from types import NoneType as SignalsUpdate


def init_signals(module: ModuleType):
    if (
        module.__spec__ is None
        or not module.__spec__.submodule_search_locations
    ):
        return
    for i in pkgutil.iter_modules(module.__path__):
        tmp = import_module(f"{module.__name__}.{i.name}")
        if not i.ispkg:
            continue
        init_signals(tmp)


def init_streams(
    models: list[type["Document"]],
):
    for model_cls in models:
        if issubclass(model_cls, SignalsSave):
            model_cls.get_publisher(Operations.SAVE)
        if issubclass(model_cls, SignalsUpdate):
            model_cls.get_publisher(Operations.UPDATE)
