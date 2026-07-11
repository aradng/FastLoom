from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aredis_om import Field, JsonModel
else:
    try:
        from aredis_om import Field, JsonModel
    except ImportError:
        from pydantic import BaseModel as JsonModel
        from pydantic import Field


class BaseCache(JsonModel):
    class Meta:
        global_key_prefix = "cache"
        model_key_prefix = "base"
        # ^should be overriden in sub

    @property
    async def invalidate(self):
        return await self.expire(0)


class BaseTenantSettingCache(BaseCache):
    id: str = Field(primary_key=True)


class HostTenantMapping(BaseCache, index=True):  # type: ignore[call-arg]
    host: str = Field(primary_key=True)
    tenant: str = Field(index=True)

    class Meta:
        model_key_prefix = "host_mapping"


def rewrite_cache_meta(cls: type[BaseCache], **meta_fields: object) -> None:
    """Set Meta fields on `cls` and every subclass, however deep or however
    late-defined — aredis_om snapshots Meta.global_key_prefix onto each
    subclass at class-definition time rather than looking it up dynamically,
    so a plain assignment on BaseCache only reaches subclasses defined after
    this call, not ones already imported (e.g. from a service's settings.py,
    which loads before Configs.__init__ runs)."""
    for name, value in meta_fields.items():
        setattr(cls.Meta, name, value)
    for subclass in cls.__subclasses__():
        rewrite_cache_meta(subclass, **meta_fields)
