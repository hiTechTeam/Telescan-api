"""Deterministic moderation policy for user-visible profile text."""

import re
import unicodedata
from collections.abc import Iterable

from src.domain.errors import PublicContentRejected


# Keep the built-in baseline deliberately narrow to avoid rejecting harmless
# profile text. Production can extend it without a deploy through
# PUBLIC_TEXT_EXTRA_BLOCKED_TERMS (a JSON array in the environment).
_BASELINE_BLOCKED_TERMS = (
    "fuck",
    "fucking",
    "motherfucker",
    "cunt",
    "nigger",
    "nigga",
    "faggot",
    "porn",
    "porno",
    "pornography",
    "хуй",
    "хуесос",
    "пизда",
    "пиздец",
    "ебать",
    "ебаный",
    "ёбаный",
    "блядь",
    "блять",
    "порно",
)


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _term_pattern(term: str) -> re.Pattern[str] | None:
    # Punctuation and underscores may separate characters, so common attempts
    # such as "p.o.r.n" are treated the same as the plain word. Boundaries use
    # letters/digits rather than ``\w`` so Telegram underscores are separators.
    characters = [character for character in _normalized(term) if character.isalnum()]
    if not characters:
        return None
    expression = r"[\W_]*".join(re.escape(character) for character in characters)
    return re.compile(rf"(?<![^\W_]){expression}(?![^\W_])", re.UNICODE)


class PublicTextPolicy:
    """Reject a small deny-list in names, usernames, and profile descriptions."""

    def __init__(self, extra_blocked_terms: Iterable[str] = ()) -> None:
        unique_terms = dict.fromkeys((*_BASELINE_BLOCKED_TERMS, *extra_blocked_terms))
        self._patterns = tuple(
            pattern
            for term in unique_terms
            if (pattern := _term_pattern(term.strip())) is not None
        )

    def require_allowed(self, value: str | None) -> None:
        if value is None:
            return
        normalized = _normalized(value)
        if any(pattern.search(normalized) for pattern in self._patterns):
            raise PublicContentRejected()


__all__ = ["PublicTextPolicy"]
