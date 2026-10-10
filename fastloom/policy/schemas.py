from collections.abc import Iterable
from http import HTTPMethod
from typing import Literal

from pydantic import BaseModel


class Route(BaseModel, frozen=True):
    method: HTTPMethod | Literal["*"]
    path: str


def ordered(routes: Iterable[Route]) -> list[Route]:
    return sorted(routes, key=lambda r: (r.path, r.method))
