from collections.abc import Callable
from os import getenv
from typing import Any

from pydantic import ValidationInfo


def get_env_or_err(field_name: str) -> Callable[[], str]:
    def _inner() -> str:
        value = getenv(field_name)
        if value is None:
            raise ValueError(
                f"{field_name} must be set in environment or config"
            )
        return value

    return _inner


def pydantic_env_or_default(v: Any, info: ValidationInfo) -> Any:
    if info.field_name is None:
        return v
    return getenv(info.field_name, v)
