import pkgutil
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any

from beanie import View
from fastapi import APIRouter, FastAPI
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Lifespan

from core_bluprint.db.healthcheck import get_healthcheck as db_hc
from core_bluprint.db.lifehooks import init_db
from core_bluprint.db.schemas import BaseDocument
from core_bluprint.healthcheck.handler import init_healthcheck
from core_bluprint.i18n.base import CustomI18NException
from core_bluprint.i18n.handler import i18n_exception_handler
from core_bluprint.signals.healthcheck import (
    get_healthcheck as signal_hc,
)
from core_bluprint.tenant.settings import TenantConfigs as TC

Route = tuple[APIRouter, str, str]
SettingsCls = type[BaseModel]
Healthcheck = Callable[[], Coroutine[Any, Any, None]]
ExceptionHandler = Callable[
    [Request, Exception], Response | Awaitable[Response]
]
ExceptionHandlerRegister = tuple[int | type[Exception], ExceptionHandler]


def default_lifespan():
    @asynccontextmanager
    async def _identity_gen(_):
        yield

    return _identity_gen


class App(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    signals_module: ModuleType | None = None
    healthchecks: list[Healthcheck] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)
    models: list[type[BaseDocument] | type[View]] = Field(default_factory=list)
    lifespan_fn: Lifespan = Field(default_factory=default_lifespan)
    exception_handlers: list[ExceptionHandlerRegister] = Field(
        default_factory=list
    )

    @property
    def root_router(self) -> APIRouter:
        _router = APIRouter()
        for router, prefix, name in self.routes:
            _router.include_router(router, prefix=prefix, tags=[name])
        return _router

    async def load(self, app: FastAPI):
        await self.load_db()
        await self.load_signals()

    async def load_db(self):
        if not self.models:
            return
        await init_db(
            database_name=TC.general().MONGO_DATABASE,
            models=self.models,
            mongo_uri=TC.general().MONGO_URI,
        )

    async def load_signals(self):
        if not self.signals_module:
            return
        for i in pkgutil.iter_modules(self.signals_module.__path__):
            target = f"{self.signals_module.__name__}.{i.name}"
            if i.ispkg:
                target_path = Path(self.signals_module.__path__[0]) / i.name
                for j in pkgutil.iter_modules([target_path]):
                    import_module(f"{target}.{j.name}")
            else:
                import_module(target)

    def load_healthchecks(self, app: FastAPI):
        handlers: list[Healthcheck] = [
            *self.healthchecks,
        ]

        if self.models:
            handlers.append(db_hc(TC.general().MONGO_URI))  # type: ignore[attr-defined]
        if self.signals_module:
            handlers.append(signal_hc(TC.general().RABBIT_URI))  # type: ignore[attr-defined]

        init_healthcheck(
            app=app,
            healthcheck_handlers=handlers,  # type: ignore[attr-defined]
            prefix=TC.general().API_PREFIX,  # type: ignore[attr-defined]
        )

    def load_exception_handlers(self, app: FastAPI):
        for exc_class_or_status_code, handler in (
            (CustomI18NException, i18n_exception_handler),
            *self.exception_handlers,
        ):
            app.exception_handler(exc_class_or_status_code)(handler)
