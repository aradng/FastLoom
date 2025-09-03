import gettext
from collections.abc import Callable
from pathlib import Path

from babel import Locale
from babel.support import Translations
from fastapi.responses import JSONResponse
from jinja2 import Environment, FileSystemLoader
from starlette.requests import Request

from fastloom.i18n.base import CustomI18NException
from fastloom.i18n.types import Languages


def parse_locale(locale: str | None) -> str:
    try:
        return Locale.parse(locale).language
    except (ValueError, TypeError):
        return "en"


def set_locale(locale: str | None) -> Callable[[str], str]:
    language = parse_locale(locale)

    locale_dir: Path = Path.cwd() / Path("locale")
    trans = gettext.translation(
        "messages",
        localedir=locale_dir,
        languages=[language],
        fallback=True,
    )
    trans.install()
    return trans.gettext


async def i18n_exception_handler(
    request: Request, exc: CustomI18NException
) -> JSONResponse:
    locale: str | None = request.headers.get("Accept-Language")
    gt: Callable[[str], str] = set_locale(locale)
    return JSONResponse(
        status_code=exc.error_code,
        content={
            "detail": exc.message,
            "message": exc.message,
            "message_tr": gt(exc.formatted_message),
        },
    )


def get_template(
    template_name: str, locale: str | None, *args, **kwargs
) -> str:
    language = parse_locale(locale)
    env = Environment(
        loader=FileSystemLoader(Path.cwd() / "templates"),
        extensions=["jinja2.ext.i18n"],
    )
    template = env.get_template(template_name)
    translations = Translations.load("locale", [language])
    return template.render(
        gettext=translations.gettext, lang=language, **kwargs
    )


def lang_dict(fa: str, en: str | None = None) -> dict[Languages, str]:
    """Create a language dictionary using FA as base and DEFAULT"""
    result = {Languages.BASE: fa, Languages.FA: fa}
    result[Languages.EN] = en if en is not None else fa
    return result
