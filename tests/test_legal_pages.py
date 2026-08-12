import pytest
from starlette.requests import Request

from src.api.v1.server.routers.legal import (
    privacy_policy,
    resolve_language,
    terms_of_service,
)


def make_request(accept_language: str = "") -> Request:
    headers = []
    if accept_language:
        headers.append((b"accept-language", accept_language.encode()))

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
        }
    )


@pytest.mark.asyncio
async def test_privacy_page_is_public_html() -> None:
    response = await privacy_policy(make_request(), lang=None)
    body = response.body.decode()

    assert response.status_code == 200
    assert response.media_type == "text/html"
    assert response.headers["content-language"] == "en"
    assert "Privacy Policy" in body
    assert "Account and data deletion" in body
    assert "https://telescan.space/privacy" in body
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


@pytest.mark.asyncio
async def test_terms_page_supports_russian_query() -> None:
    response = await terms_of_service(make_request(), lang="ru")
    body = response.body.decode()

    assert response.status_code == 200
    assert response.headers["content-language"] == "ru"
    assert '<html lang="ru">' in body
    assert "Условия использования" in body
    assert "/privacy?lang=ru" in body


@pytest.mark.asyncio
async def test_accept_language_selects_supported_language() -> None:
    response = await privacy_policy(
        make_request("ru-RU,ru;q=0.9,en;q=0.8"),
        lang=None,
    )
    body = response.body.decode()

    assert response.headers["content-language"] == "ru"
    assert "Политика конфиденциальности" in body


def test_language_quality_is_respected() -> None:
    assert resolve_language(None, "ru;q=0.2,en;q=0.9") == "en"
    assert resolve_language("ru-RU", "en") == "ru"
