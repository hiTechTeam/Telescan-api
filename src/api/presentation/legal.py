"""Public legal pages rendered from the approved, vendored legal source."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from functools import lru_cache
from html import escape
from pathlib import Path
from string import Template
from typing import Any
from urllib.parse import urlparse

__all__ = [
    "LEGAL_SOURCE_SHA256",
    "LEGAL_VERSION",
    "render_page",
    "resolve_language",
]


SOURCE_PATH = Path(__file__).with_name("legal_documents.json")
SOURCE_BYTES = SOURCE_PATH.read_bytes()
LEGAL_SOURCE_SHA256 = hashlib.sha256(SOURCE_BYTES).hexdigest()
_SOURCE: dict[str, Any] = json.loads(SOURCE_BYTES)
LEGAL_VERSION = str(_SOURCE["legal_version"])
DOCUMENTS: dict[str, dict[str, dict[str, Any]]] = _SOURCE["documents"]

_INLINE = re.compile(
    r"\*\*(?P<strong>.+?)\*\*"
    r"|\[(?P<label>[^\]]+)\]\((?P<url>https://[^)\s]+|mailto:[^)\s]+)\)"
)


def _validate_source() -> None:
    if _SOURCE.get("schema_version") != 1:
        raise RuntimeError("Unsupported legal source schema")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", LEGAL_VERSION) is None:
        raise RuntimeError("Legal version must be an ISO date")
    try:
        date.fromisoformat(LEGAL_VERSION)
    except ValueError as error:
        raise RuntimeError("Legal version must be a valid calendar date") from error
    if set(DOCUMENTS) != {"privacy", "terms"}:
        raise RuntimeError("Legal source must contain privacy and terms")
    for kind, localized in DOCUMENTS.items():
        if set(localized) != {"en", "ru"}:
            raise RuntimeError(f"{kind} must contain en and ru")
        expected_sections: set[str] | None = None
        for language, document in localized.items():
            for key in (
                "title",
                "summary",
                "effective_date",
                "effective_label",
                "canonical_url",
            ):
                if not isinstance(document.get(key), str) or not document[key]:
                    raise RuntimeError(f"Missing {kind}.{language}.{key}")
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", document["effective_date"]) is None:
                raise RuntimeError(f"Invalid effective date for {kind}.{language}")
            try:
                date.fromisoformat(document["effective_date"])
            except ValueError as error:
                raise RuntimeError(
                    f"Invalid effective date for {kind}.{language}"
                ) from error
            _safe_url(document["canonical_url"])
            sections = document.get("sections")
            if not isinstance(sections, list) or not sections:
                raise RuntimeError(f"Missing {kind}.{language}.sections")
            section_ids = {section.get("id") for section in sections}
            if None in section_ids or len(section_ids) != len(sections):
                raise RuntimeError(f"Invalid section ids for {kind}.{language}")
            if expected_sections is None:
                expected_sections = section_ids
            elif section_ids != expected_sections:
                raise RuntimeError(f"Section mismatch for {kind}.{language}")
            for section in sections:
                if not section.get("title") or not section.get("blocks"):
                    raise RuntimeError(
                        f"Invalid section in {kind}.{language}: {section.get('id')}"
                    )
                for block in section["blocks"]:
                    block_type = block.get("type")
                    if block_type == "paragraph":
                        if not block.get("text"):
                            raise RuntimeError("Empty legal paragraph")
                    elif block_type == "list":
                        if not block.get("items"):
                            raise RuntimeError("Empty legal list")
                    else:
                        raise RuntimeError(f"Unsupported legal block: {block_type}")


def _safe_url(url: str) -> str:
    parsed = urlparse(url)
    if (
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
    ):
        return url
    if parsed.scheme == "mailto" and parsed.path and not parsed.netloc:
        return url
    raise RuntimeError("Unsupported URL in legal source")


_validate_source()


def _render_inline(text: str) -> str:
    rendered: list[str] = []
    cursor = 0
    for match in _INLINE.finditer(text):
        rendered.append(escape(text[cursor : match.start()]))
        strong = match.group("strong")
        if strong is not None:
            rendered.append(f"<strong>{escape(strong)}</strong>")
        else:
            label = escape(match.group("label"))
            url = escape(_safe_url(match.group("url")), quote=True)
            rel = ' rel="noopener"' if url.startswith("https://") else ""
            rendered.append(f'<a href="{url}"{rel}>{label}</a>')
        cursor = match.end()
    rendered.append(escape(text[cursor:]))
    return "".join(rendered)


def _render_sections(document: dict[str, Any]) -> str:
    rendered: list[str] = []
    for section in document["sections"]:
        blocks: list[str] = []
        for block in section["blocks"]:
            if block["type"] == "paragraph":
                blocks.append(f"<p>{_render_inline(block['text'])}</p>")
            else:
                items = "".join(
                    f"<li>{_render_inline(item)}</li>" for item in block["items"]
                )
                blocks.append(f"<ul>{items}</ul>")
        rendered.append(
            f'<section id="{escape(section["id"], quote=True)}">'
            f"<h2>{escape(section['title'])}</h2>{''.join(blocks)}</section>"
        )
    return "".join(rendered)


def resolve_language(requested: str | None, accept_language: str) -> str:
    if requested:
        normalized = requested.strip().lower()
        if normalized.startswith("ru"):
            return "ru"
        if normalized.startswith("en"):
            return "en"

    preferences: list[tuple[float, str]] = []
    for item in accept_language.lower().split(","):
        parts = [part.strip() for part in item.split(";")]
        language = parts[0]
        if not language.startswith(("ru", "en")):
            continue

        quality = 1.0
        for parameter in parts[1:]:
            if parameter.startswith("q="):
                try:
                    quality = float(parameter[2:])
                except ValueError:
                    quality = 0.0

        preferences.append((quality, "ru" if language.startswith("ru") else "en"))

    return max(preferences, default=(0.0, "en"))[1]


@lru_cache(maxsize=1)
def _page_template() -> Template:
    path = Path(__file__).resolve().parents[1] / "templates" / "legal.html"
    return Template(path.read_text(encoding="utf-8"))


def render_page(kind: str, language: str) -> str:
    document = DOCUMENTS[kind][language]
    other_kind = "terms" if kind == "privacy" else "privacy"
    other_document = DOCUMENTS[other_kind][language]
    opposite_language = "ru" if language == "en" else "en"
    language_name = "Русский" if language == "en" else "English"
    current_label = "Privacy" if kind == "privacy" else "Terms"
    other_label = "Terms" if kind == "privacy" else "Privacy"
    if language == "ru":
        current_label = "Конфиденциальность" if kind == "privacy" else "Условия"
        other_label = "Условия" if kind == "privacy" else "Конфиденциальность"

    return _page_template().substitute(
        current_label=current_label,
        effective_date=escape(document["effective_label"]),
        kind=kind,
        language=language,
        language_name=language_name,
        legal_hash=LEGAL_SOURCE_SHA256,
        legal_version=escape(LEGAL_VERSION),
        opposite_language=opposite_language,
        other_kind=other_kind,
        other_label=other_label,
        other_title=escape(other_document["title"]),
        sections=_render_sections(document),
        summary=escape(document["summary"]),
        title=escape(document["title"]),
    )
