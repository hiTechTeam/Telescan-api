from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Self
from urllib.parse import urlparse

import pytest

from scripts import check_legal_deployment


class FakeResponse:
    def __init__(self, final_url: str, headers: dict[str, str], body: str) -> None:
        self._final_url = final_url
        self.headers = headers
        self._body = body.encode()
        self.status = 200

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def geturl(self) -> str:
        return self._final_url

    def read(self) -> bytes:
        return self._body


def test_expected_legal_values_match_vendored_bytes() -> None:
    expected_hash, version, labels, origins = check_legal_deployment.expected_values()
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "api"
        / "presentation"
        / "legal_documents.json"
    ).read_bytes()

    assert expected_hash == hashlib.sha256(source).hexdigest()
    assert version == "2026-09-01"
    assert labels.keys() == {"privacy", "terms"}
    assert origins == {"https://tgtelescan.ru"}


def test_deployment_check_rejects_same_host_different_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(
        "https://api.tgtelescan.ru:8443/privacy",
        {
            "X-Telescan-Legal-Hash": "approved-hash",
            "X-Telescan-Legal-Version": "2026-09-01",
        },
        (
            '<meta name="telescan-legal-hash" content="approved-hash">'
            '<meta name="telescan-legal-version" content="2026-09-01">'
            "Effective September 1, 2026"
        ),
    )
    monkeypatch.setattr(
        check_legal_deployment.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: response,
    )

    with pytest.raises(RuntimeError, match="redirected outside"):
        check_legal_deployment.verify_page(
            "https://api.tgtelescan.ru",
            "privacy",
            "approved-hash",
            "2026-09-01",
            "Effective September 1, 2026",
        )


@pytest.mark.parametrize(
    "origin,allow_http_loopback",
    [
        ("http://127.0.0.1:8000", False),
        ("http://0.0.0.0:8000", True),
        ("http://127.0.0.1.evil.example:8000", True),
        ("http://user:secret@127.0.0.1:8000", True),
        ("http://127.0.0.1:8000/prefix", True),
        ("http://127.0.0.1:8000?route=privacy", True),
        ("http://127.0.0.1:8000#privacy", True),
        ("https://user:secret@api.tgtelescan.ru", False),
    ],
)
def test_origin_validation_rejects_unsafe_urls(
    origin: str,
    allow_http_loopback: bool,
) -> None:
    with pytest.raises(RuntimeError, match="credential-free HTTPS origin"):
        check_legal_deployment.validate_origin(
            origin,
            allow_http_loopback=allow_http_loopback,
        )


@pytest.mark.parametrize(
    "origin",
    ["http://127.0.0.1:8000", "http://localhost:8000/"],
)
def test_origin_validation_allows_explicit_loopback_only(origin: str) -> None:
    check_legal_deployment.validate_origin(origin, allow_http_loopback=True)


def test_explicit_loopback_replaces_public_defaults() -> None:
    assert check_legal_deployment.origins_to_verify(
        ["http://127.0.0.1:8000"],
        {"https://tgtelescan.ru"},
        allow_http_loopback=True,
    ) == {"http://127.0.0.1:8000"}


def test_default_origins_include_api_and_canonical_public_origins() -> None:
    assert check_legal_deployment.origins_to_verify(
        [],
        {"https://tgtelescan.ru"},
    ) == {"https://api.tgtelescan.ru", "https://tgtelescan.ru"}


def test_loopback_check_rejects_redirect_to_foreign_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(
        "http://localhost:8000/privacy",
        {
            "X-Telescan-Legal-Hash": "approved-hash",
            "X-Telescan-Legal-Version": "2026-09-01",
        },
        (
            '<meta name="telescan-legal-hash" content="approved-hash">'
            '<meta name="telescan-legal-version" content="2026-09-01">'
            "Effective September 1, 2026"
        ),
    )
    monkeypatch.setattr(
        check_legal_deployment.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: response,
    )

    with pytest.raises(RuntimeError, match="redirected outside"):
        check_legal_deployment.verify_page(
            "http://127.0.0.1:8000",
            "privacy",
            "approved-hash",
            "2026-09-01",
            "Effective September 1, 2026",
        )


def test_effective_ports_distinguish_https_and_http_defaults() -> None:
    assert (
        check_legal_deployment._effective_port(urlparse("https://example.com")) == 443
    )
    assert check_legal_deployment._effective_port(urlparse("http://localhost")) == 80
