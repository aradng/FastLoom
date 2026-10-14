import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from fastloom.i18n import Language
from fastloom.i18n.depends import get_language
from fastloom.i18n.handler import parse_locale


@pytest.mark.parametrize(
    ("header", "language"),
    [
        (None, "en"),
        ("", "en"),
        ("*", "en"),
        ("zz", "en"),
        ("fr", "fr"),
        ("fr-FR", "fr"),
        ("fr_FR", "fr"),
        ("zh-Hans-CN", "zh"),
        ("ar,en;q=0.8", "ar"),
        ("en-US,en;q=0.9", "en"),
    ],
)
def test_parse_locale(header: str | None, language: str):
    assert parse_locale(header) == language


def test_get_language_sets_context_for_the_route():
    app = FastAPI(dependencies=[Depends(get_language)])

    @app.get("/language")
    async def language() -> str:
        return Language.get()

    client = TestClient(app)
    response = client.get("/language", headers={"Accept-Language": "ar-SA"})
    assert response.json() == "ar"
    assert "Accept-Language" in response.headers["vary"]
    assert client.get("/language").json() == "en"
