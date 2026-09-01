from enum import StrEnum


class LinkCodeStatus(StrEnum):
    ISSUED = "issued"
    CONSUMED = "consumed"
    REVOKED = "revoked"


class ConfirmationAction(StrEnum):
    LOGOUT_ALL = "logout_all"


class ConfirmationStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class TelegramPhotoState(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNCHANGED = "unchanged"


class ReportReason(StrEnum):
    SPAM = "spam"
    HARASSMENT = "harassment"
    INAPPROPRIATE = "inappropriate"
    IMPERSONATION = "impersonation"
    OTHER = "other"


class ReportStatus(StrEnum):
    PENDING = "pending"
    REVIEWING = "reviewing"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class AccountMergeStatus(StrEnum):
    PREPARED = "prepared"
    MIGRATING = "migrating"
    MONGO_COMPLETE = "mongo_complete"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AccountDeletionStatus(StrEnum):
    PREPARED = "prepared"
    DB_COMPLETE = "db_complete"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ReportPhotoEvidenceStatus(StrEnum):
    AVAILABLE = "available"
    ABSENT = "absent"
    COPY_FAILED = "copy_failed"
