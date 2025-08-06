import importlib
import importlib.util
import logging
import re
import sys
from pathlib import Path
from re import Pattern
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from core_bluprint.launcher.schemas import App

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


def get_settings_cls() -> SettingsCls:
    return _dynamic_import("settings").Settings


class EndpointFilter(logging.Filter):
    def __init__(
        self, excluded_endpoints: tuple[Pattern | str, ...] = ()
    ) -> None:
        super().__init__()
        self.excluded_endpoints = excluded_endpoints

    def filter(self, record: logging.LogRecord) -> bool:
        if not record.args or len(record.args) < 3:
            return True
        endpoint: str = record.args[2]  # type: ignore[assignment, index]
        return not any(
            re.match(exp, endpoint) for exp in self.excluded_endpoints
        )
