from pathlib import Path

import pytest
from starlette.requests import Request

from src.api.presentation.legal import resolve_language
from src.api.routers.legal import privacy_policy, terms_of_service


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
    assert "Effective August 17, 2026" in body
    assert "supporting service providers" in body
    assert "WireGuard" not in body
    assert "Account and data deletion" in body
    assert "https://tgtelescan.ru/privacy" in body
    assert '<link rel="stylesheet" href="/public/legal.css">' in body
    assert "<style>" not in body
    assert '<span class="brand">Telescan</span>' in body
    assert '<a class="brand"' not in body
    assert 'class="mark"' not in body
    assert "Your data, clearly explained" not in body
    assert "style-src 'self'" in response.headers["content-security-policy"]
    assert "'unsafe-inline'" not in response.headers["content-security-policy"]
    assert "img-src 'self' data:" in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


@pytest.mark.asyncio
async def test_terms_page_supports_russian_query() -> None:
    response = await terms_of_service(make_request(), lang="ru")
    body = response.body.decode()

    assert response.status_code == 200
    assert response.headers["content-language"] == "ru"
    assert '<html lang="ru">' in body
    assert "Условия использования" in body
    assert "Действуют с 17 августа 2026 года" in body
    assert "поставщиков сетевой и серверной инфраструктуры" in body
    assert "WireGuard" not in body
    assert "/privacy?lang=ru" in body
    assert "Правила использования Telescan" not in body
    assert '<a class="brand"' not in body
    assert 'class="mark"' not in body


@pytest.mark.asyncio
async def test_accept_language_selects_supported_language() -> None:
    response = await privacy_policy(
        make_request("ru-RU,ru;q=0.9,en;q=0.8"),
        lang=None,
    )
    body = response.body.decode()

    assert response.headers["content-language"] == "ru"
    assert "Политика конфиденциальности" in body
    assert "Понятно о ваших данных" not in body


def test_language_quality_is_respected() -> None:
    assert resolve_language(None, "ru;q=0.2,en;q=0.9") == "en"
    assert resolve_language("ru-RU", "en") == "ru"


def test_legal_stylesheet_is_served_as_css() -> None:
    stylesheet = (
        Path(__file__).resolve().parents[1] / "public" / "legal.css"
    ).read_text(encoding="utf-8")

    assert '.nav-link[aria-current="page"]' in stylesheet
    assert "prefers-color-scheme: dark" in stylesheet
