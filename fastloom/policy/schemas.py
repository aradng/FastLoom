from collections.abc import Iterable
from http import HTTPMethod
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter


class Route(BaseModel, frozen=True):
    method: HTTPMethod | Literal["*"]
    path: str


type Role = Annotated[str, Field(min_length=1)]
type Roles = Annotated[list[Role] | set[Role], Field(min_length=1)]
type Rule = (
    Literal["public", "authenticated"]
    | Annotated[list[Roles], Field(min_length=1)]
)
RULE = TypeAdapter[Rule](Rule)
PREFIX = TypeAdapter[str](Annotated[str, Field(pattern="^/")])


class RuleLine(BaseModel, frozen=True):
    route: Route
    value: str


def ordered(routes: Iterable[Route]) -> list[Route]:
    return sorted(routes, key=lambda r: (r.path, r.method))
