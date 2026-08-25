import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from src.api.routers.auth import logout_current_session
from src.dependencies.auth import get_current_auth
from src.domain.entities import AuthContext
from src.domain.enums import ConfirmationStatus, LinkCodeStatus, TelegramPhotoState
from src.domain.errors import (
    ConfirmationNotFound,
    InvalidToken,
    InvalidLinkCode,
    SessionRevoked,
    TelegramUsernameRequired,
)
from src.infrastructure.jwt import TokenService
from src.services.codes import LinkCodeService
from src.services.photos import PhotoService
from src.services.sessions import SessionService
from src.use_cases.auth import LinkDevice, LinkTelegramAccount, SignInWithApple
from src.use_cases.confirmations import (
    DecideConfirmation,
    GetConfirmationStatus,
    RequestLogoutAll,
)
from src.use_cases.issue_link_code import IssueLinkCode
from src.use_cases.profiles import DeleteAccount, UpdateOwnBio
from tests.fakes import (
    FakeAppleIdentities,
    FakeAppleVerifier,
    FakeBlocks,
    FakeBot,
    FakeConfirmations,
    FakeLinkCodes,
    FakeReports,
    FakeSessions,
    FakeStorage,
    FakeUsers,
)


def build_auth_flow():
    users = FakeUsers()
    identities = FakeAppleIdentities()
    codes = FakeLinkCodes()
    sessions = FakeSessions()
    code_service = LinkCodeService("hmac-secret", 8)
    tokens = TokenService("jwt-secret-that-is-at-least-32-bytes", "issuer", 900)
    session_service = SessionService(sessions, tokens)
    issue = IssueLinkCode(
        users, codes, code_service, PhotoService(FakeStorage(), 1024), 300
    )
    apple = SignInWithApple(
        users,
        identities,
        FakeAppleVerifier(),
        sessions,
        session_service,
        30 * 86400,
    )
    link = LinkTelegramAccount(
        users,
        identities,
        codes,
        sessions,
        session_service,
        code_service,
    )
    link_device = LinkDevice(
        users,
        codes,
        sessions,
        session_service,
        code_service,
        30 * 86400,
    )
    return SimpleNamespace(
        users=users,
        identities=identities,
        codes=codes,
        sessions=sessions,
        tokens=tokens,
        issue=issue,
        apple=apple,
        link=link,
        link_device=link_device,
    )


async def sign_in(flow, device_id, now):
    tokens, user = await flow.apple.execute(
        "apple-identity-token", "raw-nonce-value", device_id, "Ada", now
    )
    session_id = next(
        value.id
        for value in flow.sessions.items.values()
        if value.device_id == device_id and value.user_id == str(user.id)
    )
    return tokens, user, str(user.id), session_id


@pytest.mark.asyncio
async def test_apple_sign_in_issues_session_before_telegram_link() -> None:
    flow = build_auth_flow()
    tokens, user, user_id, session_id = await sign_in(flow, uuid4(), datetime.now(UTC))

    assert tokens.refresh_token
    assert user_id == str(user.id)
    assert user.tg_id is None
    assert await flow.identities.get_by_user_id(user_id) is not None
    assert await flow.sessions.get_active(session_id, datetime.now(UTC)) is not None


@pytest.mark.asyncio
async def test_issue_revokes_previous_and_code_expires() -> None:
    flow = build_auth_flow()
    now = datetime.now(UTC)
    _, _, user_id, session_id = await sign_in(flow, uuid4(), now)
    first = await flow.issue.execute(10, "Ada", "ada", None, now)
    second = await flow.issue.execute(
        10, "Ada", "ada", None, now + timedelta(seconds=1)
    )
    assert (
        flow.codes.items[next(iter(flow.codes.items))].status == LinkCodeStatus.REVOKED
    )
    with pytest.raises(InvalidLinkCode):
        await flow.link.execute(
            first.code, user_id, session_id, now + timedelta(seconds=2)
        )
    with pytest.raises(InvalidLinkCode):
        await flow.link.execute(
            second.code, user_id, session_id, now + timedelta(minutes=6)
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("username", [None, "", "   "])
async def test_issue_requires_public_telegram_username(username: str | None) -> None:
    flow = build_auth_flow()

    with pytest.raises(TelegramUsernameRequired):
        await flow.issue.execute(10, "Ada", username, None)

    assert not flow.users.users
    assert not flow.codes.items


@pytest.mark.asyncio
async def test_bio_is_trimmed_and_can_be_removed() -> None:
    users = FakeUsers()
    user = await users.upsert_telegram_profile(10, "Ada", "ada")
    update = UpdateOwnBio(users)

    saved = await update.execute(str(user.id), "  iOS engineer.\nOpen   to meetups.  ")
    assert saved.bio == "iOS engineer. Open to meetups."

    cleared = await update.execute(str(user.id), "   ")
    assert cleared.bio is None


@pytest.mark.asyncio
async def test_telegram_profile_refresh_preserves_telescan_bio() -> None:
    flow = build_auth_flow()
    user = await flow.users.upsert_telegram_profile(10, "Ada", "ada")
    await flow.users.update_bio(str(user.id), "Looking for product designers")

    await flow.issue.execute(10, "Ada Updated", "ada_updated", None)

    assert user.tg_name == "Ada Updated"
    assert user.tg_username == "ada_updated"
    assert user.bio == "Looking for product designers"


@pytest.mark.asyncio
async def test_link_rejects_profile_that_lost_telegram_username() -> None:
    flow = build_auth_flow()
    now = datetime.now(UTC)
    _, _, user_id, session_id = await sign_in(flow, uuid4(), now)
    user = await flow.users.upsert_telegram_profile(10, "Ada", None)
    service = LinkCodeService("hmac-secret", 8)
    clear_code = service.generate()
    await flow.codes.create(
        service.hash(clear_code), str(user.id), now, now + timedelta(minutes=5)
    )

    with pytest.raises(TelegramUsernameRequired):
        await flow.link.execute(
            clear_code, user_id, session_id, now + timedelta(seconds=1)
        )

    session = await flow.sessions.get_active(session_id, now + timedelta(seconds=1))
    assert session is not None
    assert session.user_id == user_id


@pytest.mark.asyncio
async def test_issue_continues_when_telegram_photo_upload_fails() -> None:
    class FailingStorage(FakeStorage):
        async def upload(self, data, object_name, content_type):
            raise OSError("storage unavailable")

    users = FakeUsers()
    codes = FakeLinkCodes()
    issue = IssueLinkCode(
        users,
        codes,
        LinkCodeService("hmac-secret", 8),
        PhotoService(FailingStorage(), 1024),
        300,
    )

    result = await issue.execute(
        10,
        "Ada",
        "ada",
        b"\xff\xd8\xffphoto",
        datetime.now(UTC),
    )

    assert len(result.code) == 8
    user = next(iter(users.users.values()))
    assert user.photo_s3_link is None
    assert len(codes.items) == 1


@pytest.mark.asyncio
async def test_issue_removes_photo_absent_from_telegram() -> None:
    users = FakeUsers()
    codes = FakeLinkCodes()
    storage = FakeStorage()
    issue = IssueLinkCode(
        users,
        codes,
        LinkCodeService("hmac-secret", 8),
        PhotoService(storage, 1024),
        300,
    )
    user = await users.upsert_telegram_profile(10, "Ada", "ada")
    user.photo_s3_link = "https://storage.example/users/old-photo.jpg"

    result = await issue.execute(
        10,
        "Ada Updated",
        "ada_updated",
        None,
        datetime.now(UTC),
        photo_state=TelegramPhotoState.ABSENT,
    )

    assert len(result.code) == 8
    assert user.tg_name == "Ada Updated"
    assert user.tg_username == "ada_updated"
    assert user.photo_s3_link is None
    assert "https://storage.example/users/old-photo.jpg" in storage.deleted


@pytest.mark.asyncio
async def test_link_is_one_time_and_preserves_existing_telegram_profile() -> None:
    flow = build_auth_flow()
    now = datetime.now(UTC)
    _, temporary_user, user_id, session_id = await sign_in(flow, uuid4(), now)
    telegram_user = await flow.users.upsert_telegram_profile(10, "Ada", "ada")
    telegram_user.bio = "Existing profile"
    old_telescan_id = telegram_user.telescan_id
    issued = await flow.issue.execute(10, "Ada", "ada", None, now)

    results = await asyncio.gather(
        flow.link.execute(issued.code, user_id, session_id, now + timedelta(seconds=1)),
        flow.link.execute(issued.code, user_id, session_id, now + timedelta(seconds=1)),
        return_exceptions=True,
    )

    successful = [result for result in results if not isinstance(result, Exception)]
    assert len(successful) == 1
    assert sum(isinstance(result, Exception) for result in results) == 1
    _, linked_user = successful[0]
    assert linked_user.id == telegram_user.id
    assert linked_user.telescan_id == old_telescan_id
    assert linked_user.bio == "Existing profile"
    assert await flow.users.get_by_id(str(temporary_user.id)) is None
    identity = await flow.identities.get_by_user_id(str(telegram_user.id))
    assert identity is not None


@pytest.mark.asyncio
async def test_linked_apple_account_supports_multiple_devices() -> None:
    flow = build_auth_flow()
    now = datetime.now(UTC)
    _, _, first_user_id, first_session_id = await sign_in(flow, uuid4(), now)
    issued = await flow.issue.execute(10, "Ada", "ada", None, now)
    _, linked_user = await flow.link.execute(
        issued.code, first_user_id, first_session_id, now + timedelta(seconds=1)
    )

    _, second_user, _, _ = await sign_in(flow, uuid4(), now + timedelta(seconds=2))

    assert second_user.id == linked_user.id
    assert len(flow.sessions.items) == 2


@pytest.mark.asyncio
async def test_review_code_is_separate_scoped_and_one_time() -> None:
    flow = build_auth_flow()
    review_codes = FakeLinkCodes()
    review_service = LinkCodeService("review-hmac-secret", 8)
    regular_service = LinkCodeService("hmac-secret", 8)
    now = datetime.now(UTC)
    _, _, current_user_id, session_id = await sign_in(flow, uuid4(), now)
    user = await flow.users.upsert_telegram_profile(10, "Review", "telescan_review")
    clear_code = review_service.generate()
    await review_codes.create(
        review_service.hash(clear_code),
        str(user.id),
        now,
        now + timedelta(days=30),
    )
    link = LinkTelegramAccount(
        flow.users,
        flow.identities,
        flow.codes,
        flow.sessions,
        SessionService(flow.sessions, flow.tokens),
        regular_service,
        review_codes,
        review_service,
    )

    _, linked_user = await link.execute(
        clear_code, current_user_id, session_id, now + timedelta(seconds=1)
    )

    assert linked_user.id == user.id
    assert not flow.codes.items
    with pytest.raises(InvalidLinkCode):
        await link.execute(
            clear_code, str(user.id), session_id, now + timedelta(seconds=2)
        )


@pytest.mark.asyncio
async def test_confirmation_cancel_confirm_and_expire() -> None:
    flow = build_auth_flow()
    now = datetime.now(UTC)
    _, _, current_user_id, session_id = await sign_in(flow, uuid4(), now)
    code = await flow.issue.execute(10, "Ada", "ada", None, now)
    _, user = await flow.link.execute(code.code, current_user_id, session_id, now)
    confirmations = FakeConfirmations()
    bot = FakeBot()
    request = RequestLogoutAll(flow.users, confirmations, bot, 300)
    decide = DecideConfirmation(flow.users, confirmations, flow.sessions)
    status = GetConfirmationStatus(confirmations)
    user_id = str(user.id)

    cancelled = await request.execute(user_id, now)
    assert (
        await status.execute(cancelled.confirmation_id, user_id, now)
    ).status == ConfirmationStatus.PENDING
    with pytest.raises(ConfirmationNotFound):
        await status.execute(cancelled.confirmation_id, "another-user", now)
    await decide.execute(
        cancelled.confirmation_id, 10, ConfirmationStatus.CANCELLED, now
    )
    assert (
        await status.execute(cancelled.confirmation_id, user_id, now)
    ).status == ConfirmationStatus.CANCELLED
    assert all(session.revoked_at is None for session in flow.sessions.items.values())

    confirmed = await request.execute(user_id, now)
    await decide.execute(
        confirmed.confirmation_id, 10, ConfirmationStatus.CONFIRMED, now
    )
    assert all(
        session.revoked_at is not None for session in flow.sessions.items.values()
    )

    expired = await request.execute(user_id, now)
    result = await status.execute(
        expired.confirmation_id, user_id, now + timedelta(minutes=6)
    )
    assert result.status == ConfirmationStatus.EXPIRED
    assert len(bot.requests) == 3


@pytest.mark.asyncio
async def test_logout_revokes_only_current_session_and_blocks_it_immediately() -> None:
    flow = build_auth_flow()
    now = datetime.now(UTC)
    first_device_id = uuid4()
    second_device_id = uuid4()
    _, _, current_user_id, first_session_id = await sign_in(flow, first_device_id, now)
    first_code = await flow.issue.execute(10, "Ada", "ada", None, now)
    first_tokens, user = await flow.link.execute(
        first_code.code, current_user_id, first_session_id, now
    )
    await sign_in(flow, second_device_id, now + timedelta(seconds=1))
    second_session_id = next(
        session.id
        for session in flow.sessions.items.values()
        if session.device_id == second_device_id
    )
    user_id, first_session_id = flow.tokens.decode_access(first_tokens.access_token)
    container = SimpleNamespace(
        tokens=flow.tokens,
        sessions=flow.sessions,
        users=flow.users,
        apple_identities=flow.identities,
    )

    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=first_tokens.access_token
    )
    auth = await get_current_auth(credentials, container)
    assert auth.user_id == str(user.id)
    await logout_current_session(
        AuthContext(user_id=user_id, session_id=first_session_id), container
    )

    with pytest.raises(SessionRevoked):
        await get_current_auth(credentials, container)
    assert (
        await flow.sessions.get_active(second_session_id, datetime.now(UTC)) is not None
    )


@pytest.mark.asyncio
async def test_legacy_telegram_session_is_not_accepted_as_primary_auth() -> None:
    flow = build_auth_flow()
    now = datetime.now(UTC)
    user = await flow.users.upsert_telegram_profile(10, "Ada", "ada")
    session = await flow.sessions.create_or_replace(
        str(user.id), uuid4(), now, now + timedelta(days=30)
    )
    tokens = await SessionService(flow.sessions, flow.tokens).issue(
        str(user.id), session, now
    )
    container = SimpleNamespace(
        tokens=flow.tokens,
        sessions=flow.sessions,
        users=flow.users,
        apple_identities=flow.identities,
    )
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=tokens.access_token
    )

    with pytest.raises(InvalidToken):
        await get_current_auth(credentials, container)


@pytest.mark.asyncio
async def test_temporary_legacy_auth_is_accepted_only_when_enabled() -> None:
    flow = build_auth_flow()
    now = datetime.now(UTC)
    issued = await flow.issue.execute(10, "Ada", "ada", None, now)
    tokens, user = await flow.link_device.execute(issued.code, uuid4(), now)
    container = SimpleNamespace(
        tokens=flow.tokens,
        sessions=flow.sessions,
        users=flow.users,
        apple_identities=flow.identities,
        settings=SimpleNamespace(enable_legacy_api=True),
    )
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=tokens.access_token
    )

    auth = await get_current_auth(credentials, container)

    assert auth.user_id == str(user.id)
    assert await flow.identities.get_by_user_id(str(user.id)) is None


@pytest.mark.asyncio
async def test_account_deletion_cleans_domain_data_and_apple_identity() -> None:
    flow = build_auth_flow()
    now = datetime.now(UTC)
    _, _, current_user_id, session_id = await sign_in(flow, uuid4(), now)
    issued = await flow.issue.execute(10, "Ada", "ada", None, now)
    _, user = await flow.link.execute(issued.code, current_user_id, session_id, now)
    user.photo_s3_link = "https://storage.example/users/photo.jpg"
    confirmations = FakeConfirmations()
    review_codes = FakeLinkCodes()
    await review_codes.create(
        "review-hash",
        str(user.id),
        now,
        now + timedelta(days=30),
    )
    await confirmations.create_logout_all(str(user.id), now, now + timedelta(minutes=5))
    storage = FakeStorage()
    delete = DeleteAccount(
        flow.users,
        flow.codes,
        flow.sessions,
        confirmations,
        FakeReports(),
        FakeBlocks(),
        PhotoService(storage, 1024),
        review_codes,
        flow.identities,
    )

    await delete.execute(str(user.id))

    assert await flow.users.get_by_id(str(user.id)) is None
    assert not flow.sessions.items
    assert not flow.codes.items
    assert not confirmations.items
    assert not review_codes.items
    assert await flow.identities.get_by_user_id(str(user.id)) is None
    assert user.photo_s3_link in storage.deleted
    assert f"users/{user.telescan_id}/" in storage.deleted
