import pkgutil
from importlib import import_module
from types import ModuleType

from fastloom.db.signals import (
    BaseDocumentSignal,
    Operations,
    SignalsDelete,
    SignalsInsert,
    SignalsUpdate,
)


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
    models: list[type[BaseDocumentSignal]],
):
    for model_cls in models:
        if (
            model_cls is BaseDocumentSignal
            or model_cls is SignalsInsert
            or model_cls is SignalsUpdate
            or model_cls is SignalsDelete
        ):
            continue
        if issubclass(model_cls, SignalsInsert):
            model_cls.get_publisher(Operations.CREATE)
        if issubclass(model_cls, SignalsUpdate):
            model_cls.get_publisher(Operations.UPDATE)
        if issubclass(model_cls, SignalsDelete):
            model_cls.get_publisher(Operations.DELETE)
