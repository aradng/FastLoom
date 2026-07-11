from fastapi import HTTPException, Request

from fastloom.settings.base import FastAPISettings
from fastloom.tenant.settings import ConfigAlias as Configs


def reject_external(request: Request) -> None:
    api_prefix = Configs[FastAPISettings].general.API_PREFIX  # type: ignore[misc]
    if request.url.path.startswith(api_prefix):
        raise HTTPException(status_code=404)
