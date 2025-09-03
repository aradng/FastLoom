from collections.abc import MutableMapping
from typing import TypeVar

V = TypeVar("V")


def get_general_settings(configs: MutableMapping[str, V]) -> V:
    return next(iter(configs.values()))
