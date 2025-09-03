from contextvars import ContextVar

from fastloom.auth.schemas import UserClaims

Claims: ContextVar[UserClaims] = ContextVar("claims")
