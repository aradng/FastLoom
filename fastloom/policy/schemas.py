from collections.abc import Iterable
from http import HTTPMethod
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter


class Route(BaseModel, frozen=True):
    method: HTTPMethod | Literal["*"]
    path: str


type Roles = Annotated[list[str], Field(min_length=1)]
type Rule = (
    Literal["public", "authenticated"]
    | Annotated[list[Roles], Field(min_length=1)]
)
RULE = TypeAdapter[Rule](Rule)


def ordered(routes: Iterable[Route]) -> list[Route]:
    return sorted(routes, key=lambda r: (r.path, r.method))
