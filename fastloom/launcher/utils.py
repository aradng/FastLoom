import importlib.util
import logging
import os
import signal
import sys
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import (
    AbstractAsyncContextManager,
    AsyncExitStack,
    asynccontextmanager,
)
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from fastloom.launcher.schemas import App

SettingsCls = type[BaseModel]


def is_installed(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


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


def setup_brokers() -> None:
    from fastloom.extras import AIO_PIKA_INSTALLED, CONFLUENT_KAFKA_INSTALLED
    from fastloom.monitoring import instrument_brokers
    from fastloom.observability.settings import ObservabilitySettings
    from fastloom.signals.depends import RabbitSubscriber, RabbitSubscriptable
    from fastloom.signals.kafka.depends import KafkaSubscriber
    from fastloom.signals.kafka.settings import (
        KafkaSettings,
        KafkaSubscriptable,
    )
    from fastloom.signals.settings import RabbitmqSettings
    from fastloom.tenant.settings import ConfigAlias as Configs

    instrument_brokers(Configs[ObservabilitySettings].general)  # type: ignore[misc]
    if isinstance(
        Configs[RabbitSubscriptable].general,  # type: ignore[misc]
        RabbitmqSettings,
    ):
        RabbitSubscriber(Configs[RabbitSubscriptable].general)  # type: ignore[misc]
    elif AIO_PIKA_INSTALLED:
        logging.warning("Settings Does Not Inherit from RabbitmqSettings")
    if isinstance(
        Configs[KafkaSubscriptable].general,  # type: ignore[misc]
        KafkaSettings,
    ):
        KafkaSubscriber(Configs[KafkaSubscriptable].general)  # type: ignore[misc]
    elif CONFLUENT_KAFKA_INSTALLED:
        logging.warning("Settings Does Not Inherit from KafkaSettings")


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


def combine_lifespans[AppT](
    *lifespans: Callable[
        [AppT], AbstractAsyncContextManager[Mapping[str, Any] | None]
    ],
) -> Callable[[AppT], AbstractAsyncContextManager[dict[str, Any]]]:
    """Combine multiple lifespans into a single lifespan.

    Useful when mounting FastMCP into FastAPI and you need to run
    both your app's lifespan and the MCP server's lifespan.

    Works with both FastAPI-style lifespans (yield None) and FastMCP-style
    lifespans (yield dict). Results are merged; later lifespans override
    earlier ones on key conflicts.

    Lifespans are entered in order and exited in reverse order (LIFO).

    Example:
        ```python
        from fastmcp import FastMCP
        from fastmcp.utilities.lifespan import combine_lifespans
        from fastapi import FastAPI

        mcp = FastMCP("Tools")
        mcp_app = mcp.http_app()

        app = FastAPI(lifespan=combine_lifespans(app_lifespan, mcp_app.lifespan))
        app.mount("/mcp", mcp_app)  # MCP endpoint at /mcp
        ```

    Args:
        *lifespans: Lifespan context manager factories to combine.

    Returns:
        A combined lifespan context manager factory.
    """  # noqa: E501

    @asynccontextmanager
    async def combined(app: AppT) -> AsyncIterator[dict[str, Any]]:
        merged: dict[str, Any] = {}
        async with AsyncExitStack() as stack:
            for ls in lifespans:
                result = await stack.enter_async_context(ls(app))
                if result is not None:
                    merged.update(result)
            yield merged

    return combined
