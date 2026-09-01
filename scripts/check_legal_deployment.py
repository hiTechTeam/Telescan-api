"""Verify that deployed legal pages serve the approved source version and hash."""

from __future__ import annotations

import argparse
import hashlib
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import ParseResult, urljoin, urlparse


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "api" / "presentation" / "legal_documents.json"
DEFAULT_PUBLIC_ORIGIN = "https://api.tgtelescan.ru"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})


def _effective_port(parsed: ParseResult) -> int:
    try:
        explicit_port = parsed.port
    except ValueError as error:
        raise RuntimeError("legal deployment URL has an invalid port") from error
    if explicit_port is not None:
        return explicit_port
    return 443 if parsed.scheme == "https" else 80


def validate_origin(origin: str, *, allow_http_loopback: bool = False) -> None:
    parsed = urlparse(origin)
    credential_free_root = (
        bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )
    try:
        _effective_port(parsed)
    except RuntimeError:
        credential_free_root = False
    is_https = parsed.scheme == "https"
    is_allowed_loopback = (
        allow_http_loopback
        and parsed.scheme == "http"
        and parsed.hostname in LOOPBACK_HOSTS
    )
    if not credential_free_root or not (is_https or is_allowed_loopback):
        raise RuntimeError(
            "--base-url must be a credential-free HTTPS origin; HTTP is allowed "
            "only for 127.0.0.1/localhost with --allow-http-loopback"
        )


def origins_to_verify(
    explicit_origins: list[str],
    canonical_origins: set[str],
    *,
    allow_http_loopback: bool = False,
) -> set[str]:
    origins = (
        set(explicit_origins)
        if explicit_origins
        else {
            *canonical_origins,
            DEFAULT_PUBLIC_ORIGIN,
        }
    )
    for origin in origins:
        validate_origin(origin, allow_http_loopback=allow_http_loopback)
    return origins


def expected_values() -> tuple[str, str, dict[str, str], set[str]]:
    payload = SOURCE.read_bytes()
    data = json.loads(payload)
    labels = {
        kind: data["documents"][kind]["en"]["effective_label"]
        for kind in ("privacy", "terms")
    }
    canonical_origins = {
        f"{parsed.scheme}://{parsed.netloc}"
        for kind in ("privacy", "terms")
        for language in data["documents"][kind].values()
        if (
            (parsed := urlparse(language["canonical_url"])).scheme == "https"
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
        )
    }
    if not canonical_origins:
        raise RuntimeError("Legal source has no valid canonical HTTPS origins")
    return (
        hashlib.sha256(payload).hexdigest(),
        data["legal_version"],
        labels,
        canonical_origins,
    )


def verify_page(
    base_url: str,
    kind: str,
    expected_hash: str,
    expected_version: str,
    effective_label: str,
) -> None:
    url = urljoin(base_url.rstrip("/") + "/", kind)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html",
            "Accept-Language": "en",
            "User-Agent": "telescan-legal-deploy-check/1",
        },
    )
    with urllib.request.urlopen(
        request,
        timeout=15,
        context=ssl.create_default_context(),
    ) as response:
        final_url = urlparse(response.geturl())
        requested_url = urlparse(url)
        if (
            final_url.scheme != requested_url.scheme
            or final_url.hostname != requested_url.hostname
            or _effective_port(final_url) != _effective_port(requested_url)
            or final_url.username is not None
            or final_url.password is not None
            or final_url.path.rstrip("/") != requested_url.path.rstrip("/")
            or final_url.query
            or final_url.fragment
        ):
            raise RuntimeError(f"{url} redirected outside its verified public route")
        body = response.read().decode("utf-8")
        actual_hash = response.headers.get("X-Telescan-Legal-Hash")
        actual_version = response.headers.get("X-Telescan-Legal-Version")
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
        if actual_hash != expected_hash:
            raise RuntimeError(
                f"{url} legal hash mismatch: {actual_hash!r} != {expected_hash!r}"
            )
        if actual_version != expected_version:
            raise RuntimeError(
                f"{url} legal version mismatch: "
                f"{actual_version!r} != {expected_version!r}"
            )
        markers = (
            f'name="telescan-legal-hash" content="{expected_hash}"',
            f'name="telescan-legal-version" content="{expected_version}"',
            effective_label,
        )
        missing = [marker for marker in markers if marker not in body]
        if missing:
            raise RuntimeError(f"{url} is missing approved markers: {missing}")
    print(f"{url}: approved version {expected_version}, sha256 {expected_hash}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        action="append",
        default=[],
        help=(
            "origin that serves /privacy and /terms; may be repeated and replaces "
            "the default public origins"
        ),
    )
    parser.add_argument(
        "--allow-http-loopback",
        action="store_true",
        help=(
            "allow explicit http://127.0.0.1 or http://localhost origins for "
            "closed-ingress candidate verification"
        ),
    )
    args = parser.parse_args()
    expected_hash, expected_version, labels, canonical_origins = expected_values()
    try:
        origins = origins_to_verify(
            args.base_url,
            canonical_origins,
            allow_http_loopback=args.allow_http_loopback,
        )
        for origin in sorted(origins):
            for kind in ("privacy", "terms"):
                verify_page(
                    origin,
                    kind,
                    expected_hash,
                    expected_version,
                    labels[kind],
                )
    except (OSError, RuntimeError, UnicodeError, urllib.error.URLError) as error:
        print(f"Legal deployment verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
