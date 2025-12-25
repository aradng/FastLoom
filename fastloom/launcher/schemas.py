from collections.abc import Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from types import ModuleType
from typing import TYPE_CHECKING, Any, Self

from fastloom.cache.settings import RedisSettings
from fastloom.launcher.settings import LauncherSettings
from fastloom.signals.lifehooks import init_signals
from fastloom.signals.settings import RabbitmqSettings
from fastloom.tenant.handler import init_settings_endpoints

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
    ValidationError,
    computed_field,
    model_validator,
)
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Lifespan

from fastloom.cache.healthcheck import get_healthcheck as cache_hc
from fastloom.db.healthcheck import get_healthcheck as db_hc
from fastloom.db.lifehooks import get_models, init_db
from fastloom.db.settings import MongoSettings
from fastloom.healthcheck.handler import init_healthcheck
from fastloom.i18n.base import CustomI18NException
from fastloom.i18n.handler import i18n_exception_handler
from fastloom.settings.base import FastAPISettings
from fastloom.signals.depends import RabbitSubscriber
from fastloom.signals.healthcheck import (
    get_healthcheck as signal_hc,
)
from fastloom.tenant.settings import ConfigAlias as Configs

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
    models_module: ModuleType | None = None
    healthchecks: list[Healthcheck] = Field(default_factory=list)
    additional_instruments: list[Callable] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)
    models: list[type[Document] | type[UnionDoc] | type[View]] = Field(
        default_factory=list
    )
    lifespan_fn: Lifespan = Field(default_factory=default_lifespan)
    exception_handlers: list[ExceptionHandlerRegister] = Field(
        default_factory=list
    )
    cache_healthcheck: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def project_name(self) -> str | None:
        return self.models[0].__module__.split(".")[0] if self.models else None

    def load_routes(self, app: FastAPI):
        for router, prefix, name in self.routes:
            app.include_router(
                router,
                prefix=Configs[FastAPISettings].general.API_PREFIX + prefix,  # type: ignore[misc]
                tags=[name],
            )

    async def load(self):
        await self.load_db()
        if self.signals_module is not None:
            init_signals(self.signals_module)

    async def load_db(self):
        if not self.models:
            return
        await init_db(
            database_name=Configs[MongoSettings].general.MONGO_DATABASE,
            models=self.models + [Configs.tenant_schema.document],
            mongo_uri=Configs[MongoSettings].general.MONGO_URI,
        )

    def load_healthchecks(self, app: FastAPI):
        handlers: list[Healthcheck] = [
            *self.healthchecks,
        ]
        if self.cache_healthcheck:
            handlers.append(
                cache_hc(Configs[RedisSettings].general.REDIS_URL)  # type: ignore[misc]
            )
        if self.models:
            handlers.append(db_hc(Configs[MongoSettings].general.MONGO_URI))  # type: ignore[misc]
        if self.signals_module:
            handlers.append(signal_hc(RabbitSubscriber.router))

        init_healthcheck(app=app, healthcheck_handlers=handlers)
        # ^for docker and system healthcheck
        init_healthcheck(
            app=app,
            healthcheck_handlers=handlers,
            prefix=Configs[FastAPISettings].general.API_PREFIX,  # type: ignore[misc]
        )

    def load_system_endpoints(self, app: FastAPI):
        init_settings_endpoints(app=app, configs=Configs)
        if Configs[LauncherSettings].general.SETTINGS_PUBLIC:  # type: ignore[misc]
            init_settings_endpoints(
                app=app,
                configs=Configs,
                prefix=Configs[FastAPISettings].general.API_PREFIX,  # type: ignore[misc]
            )

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

    @model_validator(mode="after")
    def validate_signals(self) -> Self:
        if self.signals_module is not None and not isinstance(
            Configs[RabbitmqSettings].general,  # type: ignore[misc]
            RabbitmqSettings,
        ):
            raise ValidationError(
                "Settings does not inherit from RabbitmqSettings"
            )
        return self
