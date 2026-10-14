from typing import Annotated

from fastapi import Header, Response

from fastloom.i18n import Language
from fastloom.i18n.handler import parse_locale


async def get_language(
    response: Response,
    accept_language: Annotated[str | None, Header()] = None,
) -> str:
    language = parse_locale(accept_language)
    Language.set(language)
    response.headers.add_vary_header("Accept-Language")
    return language
