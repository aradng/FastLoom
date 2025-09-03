from gettext import gettext as _
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from fastloom.i18n.base import DoesNotExist
from fastloom.launcher.utils import reload_app
from fastloom.tenant.depends import TenantNotFound
from fastloom.tenant.settings import Configs


def init_settings_endpoints(
    app: FastAPI,
    configs: type[Configs[Any, BaseModel]],
    prefix: str = "",
) -> None:
    router = APIRouter()

    @router.get(f"{prefix}/tenant_schema")
    async def get_tenant_schema() -> dict[str, Any]:
        return configs.tenant_schema.get_schema()

    @router.get(f"{prefix}/tenant_settings")
    async def get_tenant_settings(tenant: str):
        try:
            return await configs.self[tenant]
        except TenantNotFound as e:
            raise DoesNotExist(_("Tenant")) from e

    @router.post(f"{prefix}/tenant_settings")
    async def set_tenant_settings(setting: dict[str, Any], tenant: str):
        old_doc = (
            old_doc.model_dump()
            if (old_doc := await configs.tenant_schema.document.get(tenant))
            is not None
            else {}
        )
        try:
            doc = configs.tenant_schema.document.model_validate(
                old_doc | setting | {"id": tenant}
            )
            configs.tenant_schema.validate(doc)
            # ^check if its valid with current default configs
        except ValidationError as e:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": _("Invalid tenant settings"),
                    "errors": e.errors(),
                },
            ) from e
        await doc.save()
        await configs.tenant_schema.cache.delete(tenant)
        # ^invalidate cache

    @router.get(f"{prefix}/reload")
    async def reload_endpoint() -> JSONResponse:
        reload_app()
        return JSONResponse(content={"status": "ok"})

    app.include_router(router, tags=["System"])
