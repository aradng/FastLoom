from collections.abc import Callable
from os import getenv


def get_env_or_err(field_name: str) -> Callable[[], str]:
    def _inner() -> str:
        value = getenv(field_name)
        if value is None:
            raise ValueError(
                f"{field_name} must be set in environment or config"
            )
        return value

    return _inner
