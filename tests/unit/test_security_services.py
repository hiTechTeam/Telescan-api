from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.domain.errors import InvalidLinkCode, RefreshTokenReused
from src.infrastructure.jwt import TokenService
from src.services.codes import LegacyCodePublisher, LinkCodeService
from src.services.sessions import SessionService
from tests.fakes import FakeSessions


def test_link_code_is_normalized_and_hmac_sha256() -> None:
    first = LinkCodeService("separate-secret", 8)
    second = LinkCodeService("other-secret", 8)
    assert first.hash(" ab cd 1234 ") == first.hash("ABCD1234")
    assert first.hash("ABCD1234") != second.hash("ABCD1234")
    assert len(first.generate()) == 8
    with pytest.raises(InvalidLinkCode):
        first.hash("not-valid!")


@pytest.mark.asyncio
async def test_legacy_code_bridge_is_explicit_and_stores_only_sha256() -> None:
    repository = SimpleNamespace(set_code_hash=AsyncMock())
    disabled = LegacyCodePublisher(repository, enabled=False)
    await disabled.publish("user-1", " abcd1234 ")
    repository.set_code_hash.assert_not_awaited()

    enabled = LegacyCodePublisher(repository, enabled=True)
    await enabled.publish("user-1", " abcd1234 ")
    repository.set_code_hash.assert_awaited_once_with(
        "user-1",
        "1635c8525afbae58c37bede3c9440844e9143727cc7c160bed665ec378d8a262",
    )

    repository.set_code_hash.reset_mock()
    production = LegacyCodePublisher(repository, enabled=True, production=True)
    await production.publish("user-1", "abcd1234")
    repository.set_code_hash.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_rotates_and_reuse_revokes_session() -> None:
    now = datetime.now(UTC)
    sessions = FakeSessions()
    tokens = TokenService("test-secret-that-is-at-least-32-bytes", "issuer", 900)
    service = SessionService(sessions, tokens)
    session = await sessions.create_or_replace(
        "user-1", __import__("uuid").uuid4(), now, now + timedelta(days=30)
    )
    issued = await service.issue("user-1", session, now)
    refreshed = await service.refresh(issued.refresh_token, now + timedelta(seconds=1))
    assert refreshed.refresh_token != issued.refresh_token

    with pytest.raises(RefreshTokenReused):
        await service.refresh(issued.refresh_token, now + timedelta(seconds=2))
    assert sessions.items[session.id].revoked_at is not None
