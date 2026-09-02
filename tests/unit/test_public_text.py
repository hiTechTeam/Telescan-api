import pytest

from src.domain.errors import PublicContentRejected
from src.services.public_text import PublicTextPolicy


@pytest.mark.parametrize(
    "value",
    [
        "friendly profile",
        "Passionate about Shiitake recipes",
        "Scunthorpe runner",
        "underscore_name",
        None,
    ],
)
def test_public_text_policy_allows_neutral_text(value: str | None) -> None:
    PublicTextPolicy().require_allowed(value)


@pytest.mark.parametrize("value", ["porn", "P.O.R.N", "hello_porn_world", "Б.Л.Я.Т.Ь"])
def test_public_text_policy_rejects_objectionable_and_obfuscated_text(
    value: str,
) -> None:
    with pytest.raises(PublicContentRejected):
        PublicTextPolicy().require_allowed(value)


def test_public_text_policy_accepts_runtime_extensions() -> None:
    policy = PublicTextPolicy(["custom forbidden phrase"])

    with pytest.raises(PublicContentRejected):
        policy.require_allowed("custom-forbidden-phrase")
