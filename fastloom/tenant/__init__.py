from contextvars import ContextVar

Tenant: ContextVar[str] = ContextVar("tenant")
