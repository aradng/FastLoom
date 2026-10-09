from collections.abc import Iterable
from typing import NamedTuple


class Route(NamedTuple):
    method: str
    path: str


def ordered(routes: Iterable[Route]) -> list[Route]:
    return sorted(routes, key=lambda r: (r.path, r.method))
