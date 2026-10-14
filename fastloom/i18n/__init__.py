from contextvars import ContextVar

DEFAULT_LANGUAGE = "en"

Language: ContextVar[str] = ContextVar("language", default=DEFAULT_LANGUAGE)
