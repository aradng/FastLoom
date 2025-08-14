from contextvars import ContextVar

from core_bluprint.auth.schemas import UserClaims

Claims: ContextVar[UserClaims] = ContextVar("claims")
