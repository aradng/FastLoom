from pathlib import Path
from typing import Annotated, Literal

import pytest
from fastapi import FastAPI, Query
from fastapi.testclient import TestClient
from mypy import api as mypy_api
from pydantic import ValidationError

from fastloom.db.schemas import BasePaginationQuery, PageLimit


class WideQuery(BasePaginationQuery[Literal[500], Literal[100]]):
    name: str | None = None


class NarrowQuery(BasePaginationQuery[Literal[50], Literal[20]]):
    pass


class OtherWideQuery(BasePaginationQuery[Literal[500], Literal[100]]):
    pass


class FieldQuery(BasePaginationQuery):
    limit: PageLimit[Literal[200]] = 50


@pytest.mark.parametrize(
    ("model", "limit", "ok"),
    [
        (BasePaginationQuery, 1, True),
        (BasePaginationQuery, 100, True),
        (BasePaginationQuery, 101, False),
        (BasePaginationQuery, 0, False),
        (WideQuery, 500, True),
        (WideQuery, 501, False),
        (NarrowQuery, 51, False),
        (FieldQuery, 200, True),
        (FieldQuery, 201, False),
    ],
)
def test_page_limit_bounds(
    model: type[BasePaginationQuery], limit: int, ok: bool
) -> None:
    if ok:
        assert model(limit=limit).limit == limit
    else:
        with pytest.raises(ValidationError):
            model(limit=limit)


def test_pagination_defaults_and_skip() -> None:
    assert BasePaginationQuery().skip == 0
    assert BasePaginationQuery().limit == 10
    assert (WideQuery().limit, NarrowQuery().limit) == (100, 20)
    assert BasePaginationQuery(offset=3, limit=20).skip == 60
    assert WideQuery.__base__ is OtherWideQuery.__base__
    with pytest.raises(ValidationError):
        BasePaginationQuery(offset=-1)


def test_default_above_cap_is_rejected() -> None:
    with pytest.raises(ValueError, match="outside"):

        class _Bad(BasePaginationQuery[Literal[50], Literal[100]]):
            pass


def test_page_limit_binds_as_query() -> None:
    app = FastAPI()

    @app.get("/model")
    def by_model(query: Annotated[WideQuery, Query()]) -> int:
        return query.limit

    @app.get("/param")
    def by_param(
        limit: Annotated[PageLimit[Literal[200]], Query()] = 10,
    ) -> int:
        return limit

    client = TestClient(app)
    assert client.get("/model").json() == 100
    assert client.get("/model", params={"limit": 501}).status_code == 422
    assert client.get("/param", params={"limit": 200}).json() == 200
    assert client.get("/param", params={"limit": 201}).status_code == 422
    params = app.openapi()["paths"]["/model"]["get"]["parameters"]
    assert {p["name"]: p["schema"].get("maximum") for p in params} == {
        "offset": None,
        "limit": 500,
        "name": None,
    }


def test_caps_type_check_as_int(tmp_path: Path) -> None:
    source = tmp_path / "use.py"
    source.write_text(
        "from typing import Literal\n"
        "from fastloom.db.schemas import BasePaginationQuery, PageLimit\n"
        "class Wide(BasePaginationQuery[Literal[500], Literal[100]]):\n"
        "    pass\n"
        "def f(\n"
        "    a: PageLimit, b: PageLimit[Literal[500]], q: Wide,\n"
        "    p: BasePaginationQuery,\n"
        ") -> str:\n"
        "    return a + b + q.limit + q.skip + p.limit\n"
    )
    config = tmp_path / "mypy.ini"
    config.write_text("[mypy]\nstrict = True\nplugins = pydantic.mypy\n")
    out, _, status = mypy_api.run(
        [
            str(source),
            "--config-file",
            str(config),
            "--no-incremental",
            "--follow-imports=silent",
        ]
    )
    assert status == 1, out
    assert out.count("error:") == 1, out
    assert 'got "int", expected "str"' in out
