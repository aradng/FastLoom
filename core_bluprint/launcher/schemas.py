import pkgutil
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, Self, TypeVar

from core_bluprint.tenant.handler import init_settings_endpoints

if TYPE_CHECKING:
    from beanie import View
    from beanie.odm.documents import Document
    from beanie.odm.union_doc import UnionDoc
else:
    try:
        from beanie import View
        from beanie.odm.documents import Document
        from beanie.odm.union_doc import UnionDoc
    except ImportError:
        from pydantic import BaseModel as Document
        from pydantic import BaseModel as UnionDoc
        from pydantic import BaseModel as View

from fastapi import APIRouter, FastAPI
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    model_validator,
)
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Lifespan

from core_bluprint.db.healthcheck import get_healthcheck as db_hc
from core_bluprint.db.lifehooks import get_models, init_db
from core_bluprint.db.settings import MongoSettings
from core_bluprint.healthcheck.handler import init_healthcheck
from core_bluprint.i18n.base import CustomI18NException
from core_bluprint.i18n.handler import i18n_exception_handler
from core_bluprint.settings.base import FastAPISettings
from core_bluprint.signals.depends import RabbitSubscriber
from core_bluprint.signals.healthcheck import (
    get_healthcheck as signal_hc,
)
from core_bluprint.tenant.settings import ConfigAlias as Configs

E = TypeVar("E", bound=Exception)
Route = tuple[APIRouter, str, str]
SettingsCls = type[BaseModel]
Healthcheck = Callable[[], Coroutine[Any, Any, None]]
ExceptionHandler = Callable[[Request, E], Response | Awaitable[Response]]
ExceptionHandlerRegister = tuple[int | type[E], ExceptionHandler]


def default_lifespan():
    @asynccontextmanager
    async def _identity_gen(_):
        yield

    return _identity_gen


class App(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    signals_module: ModuleType | None = None
    models_module: ModuleType | None = None
    healthchecks: list[Healthcheck] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)
    models: list[type[Document] | type[UnionDoc] | type[View]] = Field(
        default_factory=list
    )
    lifespan_fn: Lifespan = Field(default_factory=default_lifespan)
    exception_handlers: list[ExceptionHandlerRegister] = Field(
        default_factory=list
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def project_name(self) -> str | None:
        return self.models[0].__module__.split(".")[0] if self.models else None

    @property
    def root_router(self) -> APIRouter:
        _router = APIRouter()
        for router, prefix, name in self.routes:
            _router.include_router(router, prefix=prefix, tags=[name])
        return _router

    async def load(self, app: FastAPI):
        await self.load_db()
        self.load_signals()

    async def load_db(self):
        if not self.models:
            return
        await init_db(
            database_name=Configs[MongoSettings].general.MONGO_DATABASE,
            models=self.models + [Configs.tenant_schema.document],
            mongo_uri=Configs[MongoSettings].general.MONGO_URI,
        )

    def load_signals(self):
        if not self.signals_module:
            return
        if not hasattr(self.signals_module, "__path__"):
            return import_module(self.signals_module.__name__)
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
            handlers.append(db_hc(Configs[MongoSettings].general.MONGO_URI))  # type: ignore[misc]
        if self.signals_module:
            handlers.append(signal_hc(RabbitSubscriber.router))

        init_healthcheck(
            app=app,
            healthcheck_handlers=handlers,
            prefix=Configs[FastAPISettings].general.API_PREFIX,  # type: ignore[misc]
        )

    def load_system_endpoints(self, app: FastAPI):
        init_settings_endpoints(app=app, configs=Configs)

    def load_exception_handlers(self, app: FastAPI):
        for exc_class_or_status_code, handler in (
            (CustomI18NException, i18n_exception_handler),
            *self.exception_handlers,
        ):
            app.exception_handler(exc_class_or_status_code)(handler)

    @model_validator(mode="after")
    def module_to_models(self) -> Self:
        if self.models_module is not None and not self.models:
            self.models = get_models(self.models_module)
        return self
