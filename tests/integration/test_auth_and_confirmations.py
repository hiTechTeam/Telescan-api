import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from src.api.routers.auth import logout_current_session
from src.dependencies.auth import get_current_auth
from src.domain.entities import AuthContext
from src.domain.enums import ConfirmationStatus, LinkCodeStatus
from src.domain.errors import ConfirmationNotFound, InvalidLinkCode, SessionRevoked
from src.infrastructure.jwt import TokenService
from src.services.codes import LinkCodeService
from src.services.photos import PhotoService
from src.services.sessions import SessionService
from src.use_cases.auth import LinkDevice
from src.use_cases.confirmations import (
    DecideConfirmation,
    GetConfirmationStatus,
    RequestLogoutAll,
)
from src.use_cases.issue_link_code import IssueLinkCode
from src.use_cases.profiles import DeleteAccount
from tests.fakes import (
    FakeBot,
    FakeConfirmations,
    FakeLinkCodes,
    FakeSessions,
    FakeStorage,
    FakeUsers,
)


def build_auth_flow():
    users = FakeUsers()
    codes = FakeLinkCodes()
    sessions = FakeSessions()
    code_service = LinkCodeService("hmac-secret", 8)
    tokens = TokenService("jwt-secret-that-is-at-least-32-bytes", "issuer", 900)
    issue = IssueLinkCode(
        users, codes, code_service, PhotoService(FakeStorage(), 1024), 300
    )
    link = LinkDevice(
        users,
        codes,
        sessions,
        SessionService(sessions, tokens),
        code_service,
        30 * 86400,
    )
    return users, codes, sessions, issue, link


@pytest.mark.asyncio
async def test_issue_revokes_previous_and_code_expires() -> None:
    users, codes, _, issue, link = build_auth_flow()
    now = datetime.now(UTC)
    first = await issue.execute(10, "Ada", "ada", None, now)
    second = await issue.execute(10, "Ada", "ada", None, now + timedelta(seconds=1))
    assert codes.items[next(iter(codes.items))].status == LinkCodeStatus.REVOKED
    with pytest.raises(InvalidLinkCode):
        await link.execute(first.code, uuid4(), now + timedelta(seconds=2))
    with pytest.raises(InvalidLinkCode):
        await link.execute(second.code, uuid4(), now + timedelta(minutes=6))
    assert len(users.users) == 1


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
async def test_link_is_one_time_under_concurrency_and_supports_multiple_devices() -> (
    None
):
    _, _, sessions, issue, link = build_auth_flow()
    now = datetime.now(UTC)
    issued = await issue.execute(10, "Ada", "ada", None, now)
    results = await asyncio.gather(
        link.execute(issued.code, uuid4(), now + timedelta(seconds=1)),
        link.execute(issued.code, uuid4(), now + timedelta(seconds=1)),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, InvalidLinkCode) for result in results) == 1

    second = await issue.execute(10, "Ada", "ada", None, now + timedelta(seconds=2))
    await link.execute(second.code, uuid4(), now + timedelta(seconds=3))
    assert len(sessions.items) == 2


@pytest.mark.asyncio
async def test_confirmation_cancel_confirm_and_expire() -> None:
    users, _, sessions, issue, link = build_auth_flow()
    now = datetime.now(UTC)
    code = await issue.execute(10, "Ada", "ada", None, now)
    await link.execute(code.code, uuid4(), now)
    confirmations = FakeConfirmations()
    bot = FakeBot()
    request = RequestLogoutAll(users, confirmations, bot, 300)
    decide = DecideConfirmation(users, confirmations, sessions)
    status = GetConfirmationStatus(confirmations)
    user_id = next(iter(users.users))

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
    assert all(session.revoked_at is None for session in sessions.items.values())

    confirmed = await request.execute(user_id, now)
    await decide.execute(
        confirmed.confirmation_id, 10, ConfirmationStatus.CONFIRMED, now
    )
    assert all(session.revoked_at is not None for session in sessions.items.values())

    expired = await request.execute(user_id, now)
    result = await status.execute(
        expired.confirmation_id, user_id, now + timedelta(minutes=6)
    )
    assert result.status == ConfirmationStatus.EXPIRED
    assert len(bot.requests) == 3


@pytest.mark.asyncio
async def test_logout_revokes_only_current_session_and_blocks_it_immediately() -> None:
    users, _, sessions, issue, link = build_auth_flow()
    now = datetime.now(UTC)
    first_device_id = uuid4()
    second_device_id = uuid4()
    first_code = await issue.execute(10, "Ada", "ada", None, now)
    first_tokens, user = await link.execute(first_code.code, first_device_id, now)
    second_code = await issue.execute(
        10, "Ada", "ada", None, now + timedelta(seconds=1)
    )
    await link.execute(second_code.code, second_device_id, now + timedelta(seconds=1))
    token_service = TokenService("jwt-secret-that-is-at-least-32-bytes", "issuer", 900)
    user_id, first_session_id = token_service.decode_access(first_tokens.access_token)
    second_session_id = next(
        session.id
        for session in sessions.items.values()
        if session.device_id == second_device_id
    )
    container = SimpleNamespace(
        tokens=token_service,
        sessions=sessions,
        users=users,
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
    assert await sessions.get_active(second_session_id, datetime.now(UTC)) is not None


@pytest.mark.asyncio
async def test_account_deletion_cleans_domain_data_and_photos_separately_from_logout() -> (
    None
):
    users, codes, sessions, issue, link = build_auth_flow()
    now = datetime.now(UTC)
    issued = await issue.execute(10, "Ada", "ada", None, now)
    _, user = await link.execute(issued.code, uuid4(), now)
    user.photo_s3_link = "https://storage.example/users/photo.jpg"
    confirmations = FakeConfirmations()
    await confirmations.create_logout_all(str(user.id), now, now + timedelta(minutes=5))
    storage = FakeStorage()
    delete = DeleteAccount(
        users,
        codes,
        sessions,
        confirmations,
        PhotoService(storage, 1024),
    )

    await delete.execute(str(user.id))

    assert await users.get_by_id(str(user.id)) is None
    assert not sessions.items
    assert not codes.items
    assert not confirmations.items
    assert user.photo_s3_link in storage.deleted
    assert f"users/{user.telescan_id}/" in storage.deleted
