import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from src.domain.enums import ConfirmationStatus, LinkCodeStatus
from src.domain.errors import LinkCodeCollision


class FakeUsers:
    def __init__(self) -> None:
        self.users: dict[str, SimpleNamespace] = {}
        self.by_tg: dict[int, str] = {}

    async def upsert_telegram_profile(self, tg_id, tg_name, tg_username):
        user_id = self.by_tg.get(tg_id, f"user-{len(self.users) + 1}")
        user = self.users.get(user_id)
        if user is None:
            user = SimpleNamespace(
                id=user_id,
                telescan_id=uuid4(),
                tg_id=tg_id,
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

    async def update_photo(self, user_id, photo_url):
        self.users[user_id].photo_s3_link = photo_url
        return self.users[user_id]

    async def delete(self, user_id):
        self.users.pop(user_id, None)


class FakeLinkCodes:
    def __init__(self) -> None:
        self.items: dict[str, SimpleNamespace] = {}
        self.lock = asyncio.Lock()

    async def revoke_issued(self, user_id, now):
        for item in self.items.values():
            if item.user_id == user_id and item.status == LinkCodeStatus.ISSUED:
                item.status = LinkCodeStatus.REVOKED

    async def create(self, code_hash, user_id, now, expires_at):
        if code_hash in self.items:
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
            item.attempts += 1
            return item

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

    async def revoke_all(self, user_id, now):
        for session in self.items.values():
            if session.user_id == user_id:
                session.revoked_at = now

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

    async def delete_for_user(self, user_id):
        self.items = {
            key: value for key, value in self.items.items() if value.user_id != user_id
        }


class FakeStorage:
    def __init__(self) -> None:
        self.uploaded: dict[str, bytes] = {}
        self.deleted: list[str] = []

    async def upload(self, data, object_name, content_type):
        self.uploaded[object_name] = data
        return f"https://storage.example/{object_name}"

    async def delete_by_url(self, public_url):
        self.deleted.append(public_url)

    async def delete_user_prefix(self, telescan_id):
        self.deleted.append(f"users/{telescan_id}/")


class FakeBot:
    def __init__(self) -> None:
        self.requests = []

    async def request_logout_all_confirmation(
        self, confirmation_id, chat_id, expires_at
    ):
        self.requests.append((confirmation_id, chat_id, expires_at))
