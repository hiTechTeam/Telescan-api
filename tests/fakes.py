import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from src.domain.enums import (
    AccountDeletionStatus,
    AccountMergeStatus,
    ConfirmationStatus,
    LinkCodeStatus,
    ReportPhotoEvidenceStatus,
    ReportStatus,
)
from src.domain.errors import LinkCodeCollision
from src.domain.entities import AppleIdentityClaims
from src.domain.errors import AppleIdentityConflict


class FakeUsers:
    def __init__(self) -> None:
        self.users: dict[str, SimpleNamespace] = {}
        self.by_tg: dict[int, str] = {}

    async def create_unlinked(self):
        user_id = f"user-{len(self.users) + 1}"
        now = datetime.now(UTC)
        user = SimpleNamespace(
            id=user_id,
            telescan_id=uuid4(),
            tg_id=None,
            tg_name=None,
            tg_username=None,
            bio=None,
            photo_s3_link=None,
            created_at=now,
            updated_at=now,
        )
        self.users[user_id] = user
        return user

    async def upsert_telegram_profile(self, tg_id, tg_name, tg_username):
        user_id = self.by_tg.get(tg_id, f"user-{len(self.users) + 1}")
        user = self.users.get(user_id)
        if user is None:
            user = SimpleNamespace(
                id=user_id,
                telescan_id=uuid4(),
                tg_id=tg_id,
                bio=None,
                photo_s3_link=None,
                created_at=datetime.now(UTC),
            )
            self.users[user_id] = user
            self.by_tg[tg_id] = user_id
        user.tg_name = tg_name
        user.tg_username = tg_username
        user.updated_at = datetime.now(UTC)
        return user

    async def get_by_id(self, user_id):
        return self.users.get(user_id)

    async def get_by_telescan_id(self, telescan_id):
        return next(
            (u for u in self.users.values() if u.telescan_id == telescan_id), None
        )

    async def get_by_tg_id(self, tg_id):
        return self.users.get(self.by_tg.get(tg_id, ""))

    async def update_bio(self, user_id, bio):
        self.users[user_id].bio = bio
        return self.users[user_id]

    async def update_photo(self, user_id, photo_url):
        self.users[user_id].photo_s3_link = photo_url
        return self.users[user_id]

    async def delete(self, user_id):
        user = self.users.pop(user_id, None)
        if user is not None and getattr(user, "tg_id", None) is not None:
            self.by_tg.pop(user.tg_id, None)


class FakeAppleIdentities:
    def __init__(self) -> None:
        self.by_subject: dict[str, SimpleNamespace] = {}
        self.by_user: dict[str, SimpleNamespace] = {}

    async def get_by_subject(self, subject):
        return self.by_subject.get(subject)

    async def get_by_user_id(self, user_id):
        return self.by_user.get(user_id)

    async def create(self, subject, user_id, email, name, now):
        if subject in self.by_subject or user_id in self.by_user:
            raise AppleIdentityConflict()
        identity = SimpleNamespace(
            subject=subject,
            user_id=user_id,
            email=email,
            name=name,
            created_at=now,
            updated_at=now,
        )
        self.by_subject[subject] = identity
        self.by_user[user_id] = identity
        return identity

    async def move_to_user(self, subject, current_user_id, target_user_id, now):
        identity = self.by_subject.get(subject)
        if identity is None or identity.user_id != current_user_id:
            raise AppleIdentityConflict()
        conflict = self.by_user.get(target_user_id)
        if conflict is not None and conflict is not identity:
            raise AppleIdentityConflict()
        self.by_user.pop(current_user_id, None)
        identity.user_id = target_user_id
        identity.updated_at = now
        self.by_user[target_user_id] = identity
        return identity

    async def delete_for_user(self, user_id):
        identity = self.by_user.pop(user_id, None)
        if identity is not None:
            self.by_subject.pop(identity.subject, None)


class FakeAppleVerifier:
    def __init__(self, subject="apple-subject", email="relay@example.com") -> None:
        self.subject = subject
        self.email = email
        self.calls = []

    async def verify(self, identity_token, raw_nonce):
        self.calls.append((identity_token, raw_nonce))
        return AppleIdentityClaims(subject=self.subject, email=self.email)


class FakeLinkCodes:
    def __init__(self) -> None:
        self.items: dict[str, SimpleNamespace] = {}
        self.lock = asyncio.Lock()

    async def revoke_issued(self, user_id, now):
        for item in self.items.values():
            if item.user_id == user_id and item.status == LinkCodeStatus.ISSUED:
                item.status = LinkCodeStatus.REVOKED

    async def create(self, code_hash, user_id, now, expires_at):
        async with self.lock:
            if code_hash in self.items or any(
                item.user_id == user_id and item.status == LinkCodeStatus.ISSUED
                for item in self.items.values()
            ):
                raise LinkCodeCollision()
            item = SimpleNamespace(
                code_hash=code_hash,
                user_id=user_id,
                status=LinkCodeStatus.ISSUED,
                created_at=now,
                expires_at=expires_at,
                attempts=0,
            )
            self.items[code_hash] = item
            return item

    async def consume(self, code_hash, device_id, now):
        async with self.lock:
            item = self.items.get(code_hash)
            if (
                item is None
                or item.status != LinkCodeStatus.ISSUED
                or item.expires_at <= now
            ):
                return None
            item.status = LinkCodeStatus.CONSUMED
            item.consumed_at = now
            item.consumed_by_device_id = device_id
            item.expires_at = max(item.expires_at, now + timedelta(days=30))
            item.attempts += 1
            return item

    async def find_for_link(self, code_hash, device_id, now):
        item = self.items.get(code_hash)
        if item is None:
            return None
        if item.status == LinkCodeStatus.ISSUED and item.expires_at > now:
            return item
        if (
            item.status == LinkCodeStatus.CONSUMED
            and getattr(item, "consumed_by_device_id", None) == device_id
            and item.expires_at > now
        ):
            return item
        return None

    async def delete_for_user(self, user_id):
        self.items = {
            key: value for key, value in self.items.items() if value.user_id != user_id
        }


class FakeSessions:
    def __init__(self) -> None:
        self.items: dict[str, SimpleNamespace] = {}

    async def create_or_replace(self, user_id, device_id, now, expires_at):
        session = next(
            (
                value
                for value in self.items.values()
                if value.user_id == user_id and value.device_id == device_id
            ),
            None,
        )
        if session is None:
            session = SimpleNamespace(id=f"session-{len(self.items) + 1}")
            self.items[session.id] = session
        session.user_id = user_id
        session.device_id = device_id
        session.created_at = getattr(session, "created_at", now)
        session.last_used_at = now
        session.expires_at = expires_at
        session.revoked_at = None
        session.refresh_token_hash = ""
        return session

    async def set_refresh_hash(self, session_id, refresh_hash, now):
        self.items[session_id].refresh_token_hash = refresh_hash
        self.items[session_id].last_used_at = now

    async def get_active(self, session_id, now):
        session = self.items.get(session_id)
        if session and session.revoked_at is None and session.expires_at > now:
            return session
        return None

    async def rotate_refresh_hash(self, session_id, expected_hash, new_hash, now):
        session = await self.get_active(session_id, now)
        if session is None or session.refresh_token_hash != expected_hash:
            return False
        session.refresh_token_hash = new_hash
        session.last_used_at = now
        return True

    async def revoke(self, session_id, now):
        if session_id in self.items:
            self.items[session_id].revoked_at = now

    async def delete(self, session_id):
        self.items.pop(session_id, None)

    async def revoke_all(self, user_id, now):
        for session in self.items.values():
            if session.user_id == user_id:
                session.revoked_at = now

    async def move_to_user(self, session_id, current_user_id, target_user_id):
        session = self.items.get(session_id)
        if session is None or session.user_id != current_user_id:
            raise LookupError(session_id)
        self.items = {
            key: value
            for key, value in self.items.items()
            if key == session_id
            or not (
                value.user_id == target_user_id and value.device_id == session.device_id
            )
        }
        session.user_id = target_user_id
        return session

    async def delete_for_user(self, user_id):
        self.items = {
            key: value for key, value in self.items.items() if value.user_id != user_id
        }


class FakeConfirmations:
    def __init__(self) -> None:
        self.items: dict[UUID, SimpleNamespace] = {}

    async def create_logout_all(self, user_id, now, expires_at):
        item = SimpleNamespace(
            public_id=uuid4(),
            user_id=user_id,
            status=ConfirmationStatus.PENDING,
            created_at=now,
            expires_at=expires_at,
            telegram_chat_id=None,
            telegram_message_id=None,
        )
        self.items[item.public_id] = item
        return item

    async def register_message(self, confirmation_id, chat_id, message_id):
        item = self.items.get(confirmation_id)
        if item is None or item.status != ConfirmationStatus.PENDING:
            return None
        item.telegram_chat_id = chat_id
        item.telegram_message_id = message_id
        return item

    async def decide(self, confirmation_id, user_id, status, now):
        item = self.items.get(confirmation_id)
        if item is None or item.user_id != user_id:
            return None
        if item.status == ConfirmationStatus.PENDING and item.expires_at > now:
            item.status = status
        elif item.status == ConfirmationStatus.PENDING:
            item.status = ConfirmationStatus.EXPIRED
        return item

    async def expire(self, confirmation_id, user_id, now):
        item = self.items.get(confirmation_id)
        if (
            item
            and item.user_id == user_id
            and item.status == ConfirmationStatus.PENDING
        ):
            if item.expires_at <= now:
                item.status = ConfirmationStatus.EXPIRED
        return item

    async def list_pending(self):
        return [
            item
            for item in self.items.values()
            if item.status == ConfirmationStatus.PENDING
        ]

    async def get_for_user(self, confirmation_id, user_id):
        item = self.items.get(confirmation_id)
        return item if item and item.user_id == user_id else None

    async def delete_for_user(self, user_id):
        self.items = {
            key: value for key, value in self.items.items() if value.user_id != user_id
        }


class FakeReports:
    def __init__(self) -> None:
        self.items: dict[UUID, SimpleNamespace] = {}

    async def create(
        self,
        reporter,
        target,
        client_request_id,
        reason,
        details,
        now,
    ):
        existing = next(
            (
                item
                for item in self.items.values()
                if item.reporter_id == str(reporter.id)
                and item.client_request_id == client_request_id
            ),
            None,
        )
        if existing is not None:
            return existing
        item = SimpleNamespace(
            public_id=uuid4(),
            client_request_id=client_request_id,
            reporter_id=str(reporter.id),
            reporter_telescan_id=reporter.telescan_id,
            target_id=str(target.id),
            target_telescan_id=target.telescan_id,
            reason=reason,
            details=details,
            target_name=target.tg_name,
            target_username=target.tg_username,
            target_bio=target.bio,
            target_photo_url=None,
            target_photo_source_url=target.photo_s3_link,
            target_photo_evidence_status=(
                ReportPhotoEvidenceStatus.COPY_FAILED
                if target.photo_s3_link
                else ReportPhotoEvidenceStatus.ABSENT
            ),
            target_photo_evidence_attempts=0,
            status=ReportStatus.PENDING,
            created_at=now,
            updated_at=now,
            resolved_at=None,
            retention_until=None,
            moderator_id=None,
            moderator_note=None,
            revision=0,
            moderation_history=[],
        )
        self.items[item.public_id] = item
        return item

    async def get_by_public_id(self, report_id):
        return self.items.get(report_id)

    async def list_by_status(self, status, limit):
        items = sorted(
            self.items.values(), key=lambda item: item.created_at, reverse=True
        )
        if status is not None:
            items = [item for item in items if item.status == status]
        return items[:limit]

    async def update_status(
        self,
        report_id,
        status,
        moderator_id,
        note,
        note_is_set,
        expected_revision,
        now,
    ):
        item = self.items.get(report_id)
        if item is None or item.revision != expected_revision:
            return None
        previous_status = item.status
        item.status = status
        item.moderator_id = moderator_id
        if note_is_set:
            item.moderator_note = note
        item.revision += 1
        item.moderation_history.append(
            SimpleNamespace(
                revision=item.revision,
                from_status=previous_status,
                to_status=status,
                moderator_id=moderator_id,
                note=item.moderator_note,
                note_changed=note_is_set,
                created_at=now,
            )
        )
        item.updated_at = now
        item.resolved_at = None if status == ReportStatus.REVIEWING else now
        item.retention_until = (
            None if status == ReportStatus.REVIEWING else now + timedelta(days=180)
        )
        return item

    async def update_photo_evidence(self, report_id, evidence_url, now):
        item = self.items.get(report_id)
        if item is None:
            return None
        item.target_photo_url = evidence_url
        item.target_photo_evidence_status = ReportPhotoEvidenceStatus.AVAILABLE
        item.updated_at = now
        return item

    async def record_photo_evidence_attempt(self, report_id, now):
        item = self.items.get(report_id)
        if item is not None:
            item.target_photo_evidence_attempts += 1
            item.updated_at = now

    async def list_pending_photo_evidence(self, limit):
        return [
            item
            for item in self.items.values()
            if item.target_photo_evidence_status
            == ReportPhotoEvidenceStatus.COPY_FAILED
        ][:limit]

    async def list_due_for_cleanup(self, now, limit):
        return [
            item
            for item in self.items.values()
            if item.retention_until is not None and item.retention_until <= now
        ][:limit]

    async def delete_by_public_id(self, report_id):
        self.items.pop(report_id, None)

    async def anonymize_user(self, user_id):
        for item in self.items.values():
            if item.reporter_id == user_id:
                item.reporter_id = None
                item.reporter_telescan_id = None
            if item.target_id == user_id:
                item.target_id = None


class FakeBlocks:
    def __init__(self) -> None:
        self.items: list[SimpleNamespace] = []

    async def create(self, blocker_id, target, now):
        existing = next(
            (
                item
                for item in self.items
                if item.blocker_id == blocker_id and item.blocked_id == str(target.id)
            ),
            None,
        )
        if existing is not None:
            return existing
        item = SimpleNamespace(
            blocker_id=blocker_id,
            blocked_id=str(target.id),
            blocked_telescan_id=target.telescan_id,
            blocked_name=target.tg_name,
            blocked_username=target.tg_username,
            blocked_photo_url=target.photo_s3_link,
            created_at=now,
        )
        self.items.append(item)
        return item

    async def delete(self, blocker_id, blocked_telescan_id):
        before = len(self.items)
        self.items = [
            item
            for item in self.items
            if not (
                item.blocker_id == blocker_id
                and item.blocked_telescan_id == blocked_telescan_id
            )
        ]
        return len(self.items) != before

    async def exists_between(self, first_user_id, second_user_id):
        return any(
            (item.blocker_id == first_user_id and item.blocked_id == second_user_id)
            or (item.blocker_id == second_user_id and item.blocked_id == first_user_id)
            for item in self.items
        )

    async def list_for_user(self, blocker_id):
        return [item for item in self.items if item.blocker_id == blocker_id]

    async def delete_for_user(self, user_id):
        self.items = [
            item
            for item in self.items
            if item.blocker_id != user_id and item.blocked_id != user_id
        ]


class FakeStorage:
    def __init__(self) -> None:
        self.uploaded: dict[str, bytes] = {}
        self.deleted: list[str] = []

    async def upload(self, data, object_name, content_type):
        self.uploaded[object_name] = data
        return f"https://storage.example/{object_name}"

    async def delete_by_url(self, public_url):
        self.deleted.append(public_url)

    async def copy_by_url(self, source_url, object_name):
        self.uploaded[object_name] = self.uploaded.get(source_url, b"copied")
        return f"https://storage.example/{object_name}"

    async def delete_user_prefix(self, telescan_id):
        self.deleted.append(f"users/{telescan_id}/")

    async def delete_report_prefix(self, report_id):
        prefix = f"moderation/reports/{report_id}/"
        self.deleted.append(prefix)
        self.uploaded = {
            name: data
            for name, data in self.uploaded.items()
            if not name.startswith(prefix)
        }


class FakeBot:
    def __init__(self) -> None:
        self.requests = []

    async def request_logout_all_confirmation(
        self, confirmation_id, chat_id, expires_at
    ):
        self.requests.append((confirmation_id, chat_id, expires_at))


class FakeAccountMergeService:
    def __init__(
        self,
        users,
        identities,
        codes,
        sessions,
        blocks=None,
        reports=None,
        confirmations=None,
    ):
        self.users = users
        self.identities = identities
        self.codes = codes
        self.sessions = sessions
        self.blocks = blocks
        self.reports = reports
        self.confirmations = confirmations
        self.journals = {}

    async def get_by_source(self, source_user_id):
        return self.journals.get(source_user_id)

    async def prepare(
        self,
        source_user,
        target_user,
        apple_subject,
        code_hash,
        code_kind,
        device_id,
        now,
    ):
        source_id = str(source_user.id)
        journal = self.journals.get(source_id)
        if journal is None:
            journal = SimpleNamespace(
                id=f"merge-{len(self.journals) + 1}",
                source_user_id=source_id,
                target_user_id=str(target_user.id),
                apple_subject=apple_subject,
                source_telescan_id=source_user.telescan_id,
                source_photo_url=source_user.photo_s3_link,
                authorization_code_hash=code_hash,
                authorization_code_kind=code_kind,
                authorization_device_id=device_id,
                authorized_at=None,
                status=AccountMergeStatus.PREPARED,
            )
            self.journals[source_id] = journal
        return journal

    async def authorize(self, journal, now):
        journal.authorized_at = now
        journal.authorization_code_hash = None
        journal.authorization_code_kind = None
        journal.authorization_device_id = None
        return journal

    async def consume_and_authorize(self, journal, consume, now):
        consumed = await consume()
        if consumed is None:
            return journal, None
        return await self.authorize(journal, now), consumed

    async def continue_merge(self, journal, now):
        if journal.authorized_at is None:
            raise RuntimeError("merge is not authorized")
        source_id = str(journal.source_user_id)
        target_id = str(journal.target_user_id)
        journal.status = AccountMergeStatus.MIGRATING
        await self.identities.move_to_user(
            journal.apple_subject, source_id, target_id, now
        )
        source_sessions = [
            item for item in self.sessions.items.values() if item.user_id == source_id
        ]
        source_devices = {item.device_id for item in source_sessions}
        self.sessions.items = {
            key: item
            for key, item in self.sessions.items.items()
            if item.user_id != target_id or item.device_id not in source_devices
        }
        for item in source_sessions:
            item.user_id = target_id
        await self.codes.delete_for_user(source_id)
        if self.confirmations is not None:
            await self.confirmations.delete_for_user(source_id)
        if self.blocks is not None:
            for item in self.blocks.items:
                if item.blocker_id == source_id:
                    item.blocker_id = target_id
                if item.blocked_id == source_id:
                    item.blocked_id = target_id
            unique = {}
            for item in self.blocks.items:
                if item.blocker_id != item.blocked_id:
                    unique[(item.blocker_id, item.blocked_id)] = item
            self.blocks.items = list(unique.values())
        if self.reports is not None:
            target = await self.users.get_by_id(target_id)
            for item in self.reports.items.values():
                if item.reporter_id == source_id:
                    item.reporter_id = target_id
                    item.reporter_telescan_id = target.telescan_id
                if item.target_id == source_id:
                    item.target_id = target_id
                    item.target_telescan_id = target.telescan_id
        await self.users.delete(source_id)
        journal.status = AccountMergeStatus.COMPLETED
        return journal

    async def resume(self, source_user_id, now):
        return await self.continue_merge(self.journals[source_user_id], now)


class FakeAccountDeletionService:
    def __init__(
        self,
        users,
        identities,
        codes,
        sessions,
        confirmations,
        reports,
        blocks,
        storage,
        review_codes=None,
    ):
        self.users = users
        self.identities = identities
        self.codes = codes
        self.sessions = sessions
        self.confirmations = confirmations
        self.reports = reports
        self.blocks = blocks
        self.storage = storage
        self.review_codes = review_codes
        self.journals = {}

    async def delete(self, user_id):
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise LookupError(user_id)
        journal = SimpleNamespace(
            id=f"deletion-{len(self.journals) + 1}",
            user_id=user_id,
            telescan_id=user.telescan_id,
            photo_url=user.photo_s3_link,
            status=AccountDeletionStatus.PREPARED,
        )
        self.journals[user_id] = journal
        await self.sessions.revoke_all(user_id, datetime.now(UTC))
        await self.codes.delete_for_user(user_id)
        if self.review_codes is not None:
            await self.review_codes.delete_for_user(user_id)
        await self.confirmations.delete_for_user(user_id)
        await self.blocks.delete_for_user(user_id)
        await self.reports.anonymize_user(user_id)
        await self.sessions.delete_for_user(user_id)
        await self.identities.delete_for_user(user_id)
        await self.users.delete(user_id)
        journal.status = AccountDeletionStatus.DB_COMPLETE
        if journal.photo_url:
            await self.storage.delete_by_url(journal.photo_url)
        await self.storage.delete_user_prefix(journal.telescan_id)
        journal.status = AccountDeletionStatus.COMPLETED
