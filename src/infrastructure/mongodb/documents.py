from uuid import UUID, uuid4

from beanie import Document, PydanticObjectId
from pydantic import AwareDatetime, Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from src.domain.enums import (
    ConfirmationAction,
    ConfirmationStatus,
    LinkCodeStatus,
    ReportReason,
    ReportStatus,
)


class UserDocument(Document):
    telescan_id: UUID = Field(default_factory=uuid4)
    tg_id: int | None = None
    tg_name: str | None = None
    tg_username: str | None = None
    bio: str | None = None
    photo_s3_link: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    class Settings:
        name = "users"
        indexes = [
            IndexModel(
                [("telescan_id", ASCENDING)], unique=True, name="uniq_telescan_id"
            ),
            IndexModel(
                [("tg_id", ASCENDING)],
                unique=True,
                name="uniq_tg_id",
                partialFilterExpression={"tg_id": {"$type": "number"}},
            ),
        ]


class AppleIdentityDocument(Document):
    subject: str
    user_id: PydanticObjectId
    email: str | None = None
    name: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    class Settings:
        name = "apple_identities"
        indexes = [
            IndexModel([("subject", ASCENDING)], unique=True, name="uniq_subject"),
            IndexModel([("user_id", ASCENDING)], unique=True, name="uniq_user"),
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
            IndexModel(
                [("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expires_at"
            ),
        ]


class ReviewCodeDocument(Document):
    public_id: UUID = Field(default_factory=uuid4)
    batch_id: UUID
    code_hash: str
    user_id: PydanticObjectId
    status: LinkCodeStatus = LinkCodeStatus.ISSUED
    created_at: AwareDatetime
    expires_at: AwareDatetime
    retention_until: AwareDatetime
    issued_by: str
    consumed_at: AwareDatetime | None = None
    consumed_by_device_id: UUID | None = None
    revoked_at: AwareDatetime | None = None
    revoked_by: str | None = None

    class Settings:
        name = "review_codes"
        indexes = [
            IndexModel([("public_id", ASCENDING)], unique=True, name="uniq_public_id"),
            IndexModel([("code_hash", ASCENDING)], unique=True, name="uniq_code_hash"),
            IndexModel(
                [("batch_id", ASCENDING), ("status", ASCENDING)],
                name="batch_status",
            ),
            IndexModel(
                [("user_id", ASCENDING), ("status", ASCENDING)],
                name="user_status",
            ),
            IndexModel([("expires_at", ASCENDING)], name="expires_at"),
            IndexModel(
                [("retention_until", ASCENDING)],
                expireAfterSeconds=0,
                name="ttl_retention_until",
            ),
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
            IndexModel(
                [("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expires_at"
            ),
        ]


class RateLimitDocument(Document):
    scope_key: str
    hits: int = 0
    expires_at: AwareDatetime

    class Settings:
        name = "rate_limits"
        indexes = [
            IndexModel([("scope_key", ASCENDING)], unique=True, name="uniq_scope"),
            IndexModel(
                [("expires_at", ASCENDING)],
                expireAfterSeconds=0,
                name="ttl_expires_at",
            ),
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
            IndexModel(
                [("user_id", ASCENDING), ("status", ASCENDING)], name="user_status"
            ),
            IndexModel(
                [("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expires_at"
            ),
        ]


class ReportDocument(Document):
    public_id: UUID = Field(default_factory=uuid4)
    client_request_id: UUID
    reporter_id: PydanticObjectId | None
    reporter_telescan_id: UUID | None
    target_id: PydanticObjectId | None
    target_telescan_id: UUID
    reason: ReportReason
    details: str | None = None
    target_name: str | None = None
    target_username: str | None = None
    target_bio: str | None = None
    target_photo_url: str | None = None
    status: ReportStatus = ReportStatus.PENDING
    created_at: AwareDatetime
    updated_at: AwareDatetime
    resolved_at: AwareDatetime | None = None
    retention_until: AwareDatetime | None = None
    moderator_id: str | None = None
    moderator_note: str | None = None

    class Settings:
        name = "reports"
        indexes = [
            IndexModel([("public_id", ASCENDING)], unique=True, name="uniq_public_id"),
            IndexModel(
                [("reporter_id", ASCENDING), ("client_request_id", ASCENDING)],
                unique=True,
                name="uniq_reporter_request",
                partialFilterExpression={"reporter_id": {"$type": "objectId"}},
            ),
            IndexModel(
                [
                    ("reporter_id", ASCENDING),
                    ("target_id", ASCENDING),
                    ("reason", ASCENDING),
                    ("status", ASCENDING),
                ],
                unique=True,
                name="uniq_pending_report",
                partialFilterExpression={
                    "reporter_id": {"$type": "objectId"},
                    "target_id": {"$type": "objectId"},
                    "status": ReportStatus.PENDING,
                },
            ),
            IndexModel(
                [("status", ASCENDING), ("created_at", DESCENDING)],
                name="status_created",
            ),
            IndexModel(
                [("target_telescan_id", ASCENDING), ("created_at", DESCENDING)],
                name="target_created",
            ),
            IndexModel(
                [("retention_until", ASCENDING)],
                expireAfterSeconds=0,
                name="ttl_retention_until",
            ),
        ]


class BlockDocument(Document):
    blocker_id: PydanticObjectId
    blocked_id: PydanticObjectId
    blocked_telescan_id: UUID
    blocked_name: str | None = None
    blocked_username: str | None = None
    blocked_photo_url: str | None = None
    created_at: AwareDatetime

    class Settings:
        name = "blocks"
        indexes = [
            IndexModel(
                [("blocker_id", ASCENDING), ("blocked_id", ASCENDING)],
                unique=True,
                name="uniq_blocker_blocked",
            ),
            IndexModel(
                [("blocker_id", ASCENDING), ("created_at", DESCENDING)],
                name="blocker_created",
            ),
            IndexModel([("blocked_id", ASCENDING)], name="blocked_user"),
        ]


DOCUMENT_MODELS = [
    UserDocument,
    AppleIdentityDocument,
    LinkCodeDocument,
    ReviewCodeDocument,
    DeviceSessionDocument,
    RateLimitDocument,
    ConfirmationRequestDocument,
    ReportDocument,
    BlockDocument,
]
