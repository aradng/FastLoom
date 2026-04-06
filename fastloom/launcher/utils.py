import importlib.util
import logging
import os
import signal
import sys
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from fastloom.launcher.schemas import App

SettingsCls = type[BaseModel]


def _dynamic_import(name: str):
    if (cwd := Path.cwd()) not in sys.path:
        sys.path.insert(0, str(cwd))
    module_name = name
    module_path = Path.cwd() / f"{name}.py"

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None:
        raise ImportError(f"Failed to import {module_name}, {module_path}")
    app_module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = app_module
    assert spec.loader is not None
    spec.loader.exec_module(app_module)
    return app_module


def get_app() -> "App":
    return _dynamic_import("app").app


@lru_cache
def _get_settings_module():
    return _dynamic_import("settings")


def get_settings_cls() -> SettingsCls:
    return _get_settings_module().Settings


def get_tenant_cls() -> SettingsCls:
    try:
        return _get_settings_module().TenantSettings
    except AttributeError:
        logging.debug("No TenantSettings Found In settings.py")
        return BaseModel


def reload_app():
    import inspect
    from pathlib import Path

    from fastloom.launcher.settings import LauncherSettings
    from fastloom.tenant.settings import ConfigAlias as Configs

    Path(
        next(
            filter(
                lambda x: __name__.split(".")[0] not in x.filename,
                inspect.stack(),
            )
        ).filename
    ).touch()
    if not Configs[LauncherSettings].general.DEBUG:
        os.kill(os.getppid(), signal.SIGHUP)


def is_installed(module: str) -> bool:
    return importlib.util.find_spec(module) is not None
