from uuid import UUID, uuid4

from beanie import Document, PydanticObjectId
from pydantic import AwareDatetime, Field
from pymongo import ASCENDING, IndexModel

from src.domain.enums import ConfirmationAction, ConfirmationStatus, LinkCodeStatus


class UserDocument(Document):
    telescan_id: UUID = Field(default_factory=uuid4)
    tg_id: int
    tg_name: str | None = None
    tg_username: str | None = None
    photo_s3_link: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    class Settings:
        name = "users"
        indexes = [
            IndexModel([("telescan_id", ASCENDING)], unique=True, name="uniq_telescan_id"),
            IndexModel([("tg_id", ASCENDING)], unique=True, name="uniq_tg_id"),
        ]


class LinkCodeDocument(Document):
    code_hash: str
    user_id: PydanticObjectId
    status: LinkCodeStatus = LinkCodeStatus.ISSUED
    created_at: AwareDatetime
    expires_at: AwareDatetime
    consumed_at: AwareDatetime | None = None
    consumed_by_device_id: UUID | None = None
    attempts: int = 0

    class Settings:
        name = "link_codes"
        indexes = [
            IndexModel([("code_hash", ASCENDING)], unique=True, name="uniq_code_hash"),
            IndexModel(
                [("user_id", ASCENDING), ("status", ASCENDING)],
                name="user_status",
            ),
            IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expires_at"),
        ]


class DeviceSessionDocument(Document):
    user_id: PydanticObjectId
    device_id: UUID
    refresh_token_hash: str
    created_at: AwareDatetime
    last_used_at: AwareDatetime
    expires_at: AwareDatetime
    revoked_at: AwareDatetime | None = None

    class Settings:
        name = "device_sessions"
        indexes = [
            IndexModel(
                [("user_id", ASCENDING), ("device_id", ASCENDING)],
                unique=True,
                name="uniq_user_device",
            ),
            IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expires_at"),
        ]


class ConfirmationRequestDocument(Document):
    public_id: UUID = Field(default_factory=uuid4)
    user_id: PydanticObjectId
    action: ConfirmationAction
    status: ConfirmationStatus = ConfirmationStatus.PENDING
    created_at: AwareDatetime
    expires_at: AwareDatetime
    telegram_chat_id: int | None = None
    telegram_message_id: int | None = None

    class Settings:
        name = "confirmation_requests"
        indexes = [
            IndexModel([("public_id", ASCENDING)], unique=True, name="uniq_public_id"),
            IndexModel([("user_id", ASCENDING), ("status", ASCENDING)], name="user_status"),
            IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expires_at"),
        ]


DOCUMENT_MODELS = [
    UserDocument,
    LinkCodeDocument,
    DeviceSessionDocument,
    ConfirmationRequestDocument,
]
