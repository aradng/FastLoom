from gettext import gettext as _
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core_bluprint.i18n.base import DoesNotExist
from core_bluprint.launcher.utils import reload_app
from core_bluprint.tenant.depends import TenantNotFound
from core_bluprint.tenant.settings import Configs


def init_settings_endpoints(
    app: FastAPI,
    configs: type[Configs[Any, BaseModel]],
    prefix: str = "",
) -> None:
    router = APIRouter()

    @router.get("/tenant_schema")
    @router.get(f"{prefix}/tenant_schema")
    async def get_tenant_schema() -> dict[str, Any]:
        return configs.tenant_schema.get_schema()

    @router.get("/tenant_settings")
    @router.get(f"{prefix}/tenant_settings")
    async def get_tenant_settings(tenant: str):
        try:
            return await configs.self[tenant]
        except TenantNotFound as e:
            raise DoesNotExist(_("Tenant")) from e

    @router.post("/tenant_settings")
    @router.post(f"{prefix}/tenant_settings")
    async def set_tenant_settings(setting: dict[str, Any], tenant: str):
        doc = configs.tenant_schema.document.model_validate(
            setting | {"id": tenant}
        )
        configs.tenant_schema.validate(doc)
        # ^check if its valid with current default configs
        await doc.save()
        await configs.tenant_schema.cache.delete(tenant)
        # ^invalidate cache

    @router.get("/reload")
    @router.get(f"{prefix}/reload")
    async def reload_endpoint() -> JSONResponse:
        reload_app()
        return JSONResponse(content={"status": "ok"})

    app.include_router(router, tags=["System"])
