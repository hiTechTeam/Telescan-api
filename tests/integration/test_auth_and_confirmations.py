import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from src.api.routers.auth import logout_current_session
from src.dependencies.auth import get_current_auth
from src.domain.entities import AuthContext
from src.domain.enums import (
    ConfirmationStatus,
    LinkCodeStatus,
    ReportReason,
    TelegramPhotoState,
)
from src.domain.errors import (
    ConfirmationNotFound,
    InvalidToken,
    InvalidLinkCode,
    PublicContentRejected,
    SessionRevoked,
    TelegramIdentityConflict,
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
from src.use_cases.profiles import DeleteAccount, UpdateOwnBio, UpdateOwnPhoto
from tests.fakes import (
    FakeAccountDeletionService,
    FakeAccountMergeService,
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


class NoopAccountOperationGuard:
    async def is_fenced(self, _user_id):
        return False

    @asynccontextmanager
    async def admit(self, _user_id):
        yield


def build_auth_flow():
    users = FakeUsers()
    identities = FakeAppleIdentities()
    codes = FakeLinkCodes()
    sessions = FakeSessions()
    confirmations = FakeConfirmations()
    reports = FakeReports()
    blocks = FakeBlocks()
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
    merges = FakeAccountMergeService(
        users,
        identities,
        codes,
        sessions,
        blocks,
        reports,
        confirmations,
    )
    link = LinkTelegramAccount(
        users,
        identities,
        codes,
        sessions,
        session_service,
        code_service,
        account_merges=merges,
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
        confirmations=confirmations,
        reports=reports,
        blocks=blocks,
        merges=merges,
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
async def test_concurrent_link_code_issuance_leaves_exactly_one_active() -> None:
    flow = build_auth_flow()
    now = datetime.now(UTC)

    issued = await asyncio.gather(
        flow.issue.execute(10, "Ada", "ada", None, now),
        flow.issue.execute(10, "Ada", "ada", None, now),
    )

    active = [
        item
        for item in flow.codes.items.values()
        if item.status == LinkCodeStatus.ISSUED
    ]
    assert len(issued) == 2
    assert len(active) == 1


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
async def test_objectionable_bio_is_rejected_without_changing_profile() -> None:
    users = FakeUsers()
    user = await users.upsert_telegram_profile(10, "Ada", "ada")
    await users.update_bio(str(user.id), "Original profile")

    with pytest.raises(PublicContentRejected):
        await UpdateOwnBio(users).execute(str(user.id), "P.O.R.N")

    assert user.bio == "Original profile"


@pytest.mark.asyncio
async def test_objectionable_telegram_profile_is_rejected_before_creation() -> None:
    flow = build_auth_flow()

    with pytest.raises(PublicContentRejected):
        await flow.issue.execute(10, "P.O.R.N", "ada", None)

    assert not flow.users.users
    assert not flow.codes.items


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
async def test_photo_replacement_updates_database_before_deleting_old_object() -> None:
    users = FakeUsers()
    user = await users.create_unlinked()
    old_url = "https://storage.example/users/old-photo.jpg"
    user.photo_s3_link = old_url
    storage = FakeStorage()
    photos = UpdateOwnPhoto(users, PhotoService(storage, 1024))

    updated = await photos.replace(str(user.id), b"\xff\xd8\xffnew-photo")

    assert updated.photo_s3_link != old_url
    assert old_url in storage.deleted
    assert updated.photo_s3_link not in storage.deleted


@pytest.mark.asyncio
async def test_photo_replacement_cleans_new_object_when_database_update_fails() -> None:
    class FailingPhotoUpdateUsers(FakeUsers):
        async def update_photo(self, user_id, photo_url):
            raise OSError("database unavailable")

    users = FailingPhotoUpdateUsers()
    user = await users.create_unlinked()
    old_url = "https://storage.example/users/old-photo.jpg"
    user.photo_s3_link = old_url
    storage = FakeStorage()
    photos = UpdateOwnPhoto(users, PhotoService(storage, 1024))

    with pytest.raises(OSError, match="database unavailable"):
        await photos.replace(str(user.id), b"\xff\xd8\xffnew-photo")

    assert user.photo_s3_link == old_url
    assert old_url not in storage.deleted
    uploaded_url = next(
        f"https://storage.example/{object_name}" for object_name in storage.uploaded
    )
    assert uploaded_url in storage.deleted


@pytest.mark.asyncio
async def test_photo_deletion_can_retry_storage_cleanup_after_database_update() -> None:
    class FailingOnceDeleteStorage(FakeStorage):
        def __init__(self) -> None:
            super().__init__()
            self.should_fail = True

        async def delete_by_url(self, public_url):
            if self.should_fail:
                self.should_fail = False
                raise OSError("storage unavailable")
            await super().delete_by_url(public_url)

    users = FakeUsers()
    user = await users.create_unlinked()
    user.photo_s3_link = "https://storage.example/users/photo.jpg"
    storage = FailingOnceDeleteStorage()
    photos = UpdateOwnPhoto(users, PhotoService(storage, 1024))

    with pytest.raises(OSError, match="storage unavailable"):
        await photos.delete(str(user.id))

    assert user.photo_s3_link is None

    updated = await photos.delete(str(user.id))

    assert updated.photo_s3_link is None
    assert f"users/{user.telescan_id}/" in storage.deleted


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
    # The same device may safely retry a consumed code after the durable merge
    # journal exists.  Both concurrent calls may therefore converge on the
    # same canonical account, or one may lose the in-memory fake's race.
    assert successful
    _, linked_user = successful[0]
    assert linked_user.id == telegram_user.id
    assert linked_user.telescan_id == old_telescan_id
    assert linked_user.bio == "Existing profile"
    assert await flow.users.get_by_id(str(temporary_user.id)) is None
    identity = await flow.identities.get_by_user_id(str(telegram_user.id))
    assert identity is not None


@pytest.mark.asyncio
async def test_consumed_link_proof_cannot_resume_after_30_days() -> None:
    flow = build_auth_flow()
    now = datetime.now(UTC)
    device_id = uuid4()
    _, _, user_id, session_id = await sign_in(flow, device_id, now)
    await flow.users.upsert_telegram_profile(10, "Ada", "ada")
    issued = await flow.issue.execute(10, "Ada", "ada", None, now)
    code_hash = LinkCodeService("hmac-secret", 8).hash(issued.code)
    consumed = await flow.codes.consume(code_hash, device_id, now)
    assert consumed is not None
    flow.sessions.items[session_id].expires_at = now + timedelta(days=31)

    with pytest.raises(InvalidLinkCode):
        await flow.link.execute(
            issued.code,
            user_id,
            session_id,
            now + timedelta(days=30, seconds=1),
        )


@pytest.mark.asyncio
async def test_merge_moves_all_relations_and_preserves_canonical_profile() -> None:
    flow = build_auth_flow()
    now = datetime.now(UTC)
    first_device = uuid4()
    _, source, source_id, session_id = await sign_in(flow, first_device, now)
    second_source_session = await flow.sessions.create_or_replace(
        source_id,
        uuid4(),
        now,
        now + timedelta(days=30),
    )
    source.bio = "placeholder bio"
    source.photo_s3_link = "https://storage.example/users/source/live.jpg"

    target = await flow.users.upsert_telegram_profile(10, "Canonical", "canonical")
    target.bio = "canonical bio"
    target_non_conflicting_session = await flow.sessions.create_or_replace(
        str(target.id), uuid4(), now, now + timedelta(days=30)
    )
    target_conflicting_session = await flow.sessions.create_or_replace(
        str(target.id), first_device, now, now + timedelta(days=30)
    )
    target.photo_s3_link = "https://storage.example/users/target/live.jpg"
    canonical_telescan_id = target.telescan_id
    third = await flow.users.upsert_telegram_profile(11, "Third", "third")
    await flow.blocks.create(source_id, third, now)
    await flow.blocks.create(str(third.id), source, now)
    outbound_report = await flow.reports.create(
        source, third, uuid4(), ReportReason.OTHER, "outbound", now
    )
    inbound_report = await flow.reports.create(
        third, source, uuid4(), ReportReason.OTHER, "inbound", now
    )
    await flow.confirmations.create_logout_all(
        source_id, now, now + timedelta(minutes=5)
    )
    await flow.codes.create(
        "source-pending-code",
        source_id,
        now,
        now + timedelta(minutes=5),
    )
    issued = await flow.issue.execute(10, "Canonical", "canonical", None, now)

    _, linked = await flow.link.execute(
        issued.code, source_id, session_id, now + timedelta(seconds=1)
    )

    assert linked.id == target.id
    assert linked.telescan_id == canonical_telescan_id
    assert linked.bio == "canonical bio"
    assert linked.photo_s3_link.endswith("/target/live.jpg")
    assert await flow.users.get_by_id(source_id) is None
    assert all(
        session.user_id == str(target.id) for session in flow.sessions.items.values()
    )
    assert second_source_session.user_id == str(target.id)
    assert target_non_conflicting_session.id in flow.sessions.items
    assert target_conflicting_session.id not in flow.sessions.items
    assert not any(
        item.user_id == source_id for item in flow.confirmations.items.values()
    )
    assert not any(item.user_id == source_id for item in flow.codes.items.values())
    assert outbound_report.reporter_id == str(target.id)
    assert inbound_report.target_id == str(target.id)
    assert all(
        source_id not in {item.blocker_id, item.blocked_id}
        for item in flow.blocks.items
    )


@pytest.mark.asyncio
async def test_link_conflict_preflight_does_not_consume_code() -> None:
    flow = build_auth_flow()
    now = datetime.now(UTC)
    _, _, source_id, session_id = await sign_in(flow, uuid4(), now)
    target = await flow.users.upsert_telegram_profile(10, "Target", "target")
    await flow.identities.create(
        "different-apple-subject",
        str(target.id),
        None,
        None,
        now,
    )
    issued = await flow.issue.execute(10, "Target", "target", None, now)
    code_hash = LinkCodeService("hmac-secret", 8).hash(issued.code)

    with pytest.raises(TelegramIdentityConflict):
        await flow.link.execute(
            issued.code, source_id, session_id, now + timedelta(seconds=1)
        )

    assert flow.codes.items[code_hash].status == LinkCodeStatus.ISSUED
    assert not flow.merges.journals


@pytest.mark.asyncio
async def test_prepared_merge_rejects_a_different_authorization_code() -> None:
    flow = build_auth_flow()
    now = datetime.now(UTC)
    device_id = uuid4()
    _, source, source_id, session_id = await sign_in(flow, device_id, now)
    target = await flow.users.upsert_telegram_profile(10, "Target", "target")
    first = await flow.issue.execute(10, "Target", "target", None, now)
    first_hash = LinkCodeService("hmac-secret", 8).hash(first.code)
    await flow.merges.prepare(
        source,
        target,
        "apple-subject",
        first_hash,
        "link",
        device_id,
        now,
    )
    second = await flow.issue.execute(
        10, "Target", "target", None, now + timedelta(seconds=1)
    )
    second_hash = LinkCodeService("hmac-secret", 8).hash(second.code)

    with pytest.raises(InvalidLinkCode):
        await flow.link.execute(
            second.code,
            source_id,
            session_id,
            now + timedelta(seconds=2),
        )

    assert flow.codes.items[second_hash].status == LinkCodeStatus.ISSUED
    assert flow.merges.journals[source_id].authorization_code_hash == first_hash


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
        flow.merges,
    )

    _, linked_user = await link.execute(
        clear_code, current_user_id, session_id, now + timedelta(seconds=1)
    )

    assert linked_user.id == user.id
    assert not flow.codes.items
    _, retried_user = await link.execute(
        clear_code, str(user.id), session_id, now + timedelta(seconds=2)
    )
    assert retried_user.id == user.id


@pytest.mark.asyncio
async def test_confirmation_cancel_confirm_and_expire() -> None:
    flow = build_auth_flow()
    now = datetime.now(UTC)
    _, _, current_user_id, session_id = await sign_in(flow, uuid4(), now)
    code = await flow.issue.execute(10, "Ada", "ada", None, now)
    _, user = await flow.link.execute(code.code, current_user_id, session_id, now)
    confirmations = flow.confirmations
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
        account_operation_guard=NoopAccountOperationGuard(),
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
async def test_telegram_first_auth_is_accepted_only_when_enabled() -> None:
    flow = build_auth_flow()
    now = datetime.now(UTC)
    issued = await flow.issue.execute(10, "Ada", "ada", None, now)
    tokens, user = await flow.link_device.execute(issued.code, uuid4(), now)
    container = SimpleNamespace(
        tokens=flow.tokens,
        sessions=flow.sessions,
        users=flow.users,
        apple_identities=flow.identities,
        settings=SimpleNamespace(enable_telegram_first_auth=True),
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
    deletions = FakeAccountDeletionService(
        flow.users,
        flow.identities,
        flow.codes,
        flow.sessions,
        confirmations,
        flow.reports,
        flow.blocks,
        storage,
        review_codes,
    )
    delete = DeleteAccount(deletions)

    await delete.execute(str(user.id))

    assert await flow.users.get_by_id(str(user.id)) is None
    assert not flow.sessions.items
    assert not flow.codes.items
    assert not confirmations.items
    assert not review_codes.items
    assert await flow.identities.get_by_user_id(str(user.id)) is None
    assert user.photo_s3_link in storage.deleted
    assert f"users/{user.telescan_id}/" in storage.deleted
