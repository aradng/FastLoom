from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field, PlainSerializer


def exclude_none_serializer(value: dict[Any, str | None]) -> dict[Any, str]:
    return {k: v for k, v in value.items() if v is not None}


class Languages(StrEnum):
    BASE = "BASE"
    EN = "EN"
    FA = "FA"


TranslatedValue = Annotated[str | None, Field(None, max_length=2000)]


Translation = Annotated[
    dict[Languages, TranslatedValue],
    Field(default_factory=dict),
    PlainSerializer(exclude_none_serializer, return_type=dict[Languages, str]),
]
