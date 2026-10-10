import ast
from collections.abc import Iterable
from http import HTTPMethod
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter


class PolicySourceError(Exception): ...


class Route(BaseModel, frozen=True):
    method: HTTPMethod | Literal["*"]
    path: str


type Role = Annotated[str, Field(min_length=1)]
type RoleSet = Annotated[list[Role] | set[Role], Field(min_length=1)]
type Rule = (
    Literal["public", "authenticated"]
    | Annotated[list[RoleSet], Field(min_length=1)]
)
RULE_ADAPTER = TypeAdapter[Rule](Rule)
PREFIX_ADAPTER = TypeAdapter[str](Annotated[str, Field(pattern=r"^/[^{}]*$")])


def valid(value: str) -> bool:
    if "'" in value:
        return False
    try:
        RULE_ADAPTER.validate_python(ast.literal_eval(value), strict=True)
    except (ValueError, SyntaxError, TypeError):
        return False
    return True


class RuleLine(BaseModel, frozen=True):
    route: Route
    value: str

    @property
    def valid(self) -> bool:
        return valid(self.value)


class ScopeLine(BaseModel, frozen=True):
    prefix: str
    value: str

    @property
    def valid(self) -> bool:
        return valid(self.value)


def ordered(routes: Iterable[Route]) -> list[Route]:
    return sorted(routes, key=lambda r: (r.path, r.method))
