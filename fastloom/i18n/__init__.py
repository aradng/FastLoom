from contextvars import ContextVar

Language: ContextVar[str] = ContextVar("language", default="en")
