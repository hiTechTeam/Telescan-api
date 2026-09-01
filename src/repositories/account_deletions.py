from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from beanie import PydanticObjectId
from pymongo import ReturnDocument

from src.domain.enums import AccountDeletionStatus, AccountMergeStatus
from src.domain.errors import AccountOperationConflict
from src.domain.ports import AccountOperationFenceRepositoryPort
from src.infrastructure.mongodb.documents import (
    AccountDeletionDocument,
    AccountMergeDocument,
    AppleIdentityDocument,
    BlockDocument,
    ConfirmationRequestDocument,
    DeviceSessionDocument,
    LinkCodeDocument,
    ReportDocument,
    ReviewCodeDocument,
    UserDocument,
)


class AccountDeletionRepository:
    """Journaled, resumable account deletion for standalone MongoDB."""

    def __init__(
        self,
        fences: AccountOperationFenceRepositoryPort,
        after_journal_persisted: Callable[[], Awaitable[None]] | None = None,
        before_terminal: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._fences = fences
        self._after_journal_persisted = after_journal_persisted
        self._before_terminal = before_terminal

    async def get_by_user(self, user_id: str) -> AccountDeletionDocument | None:
        if not PydanticObjectId.is_valid(user_id):
            return None
        raw = await AccountDeletionDocument.get_pymongo_collection().find_one(
            {
                "user_id": PydanticObjectId(user_id),
                "status": {"$ne": AccountDeletionStatus.CANCELLED},
            }
        )
        return AccountDeletionDocument.model_validate(raw) if raw else None

    async def has_active_for_user(self, user_id: str) -> bool:
        if not PydanticObjectId.is_valid(user_id):
            return False
        raw = await AccountDeletionDocument.get_pymongo_collection().find_one(
            {
                "user_id": PydanticObjectId(user_id),
                "status": {
                    "$in": [
                        AccountDeletionStatus.PREPARED,
                        AccountDeletionStatus.DB_COMPLETE,
                        AccountDeletionStatus.COMPLETED,
                    ]
                },
            },
            {"_id": 1},
        )
        return raw is not None

    async def prepare(
        self,
        user: Any,
        now: datetime,
        journal_id: str | None = None,
    ) -> AccountDeletionDocument:
        user_id = PydanticObjectId(str(getattr(user, "id")))
        merge = await AccountMergeDocument.get_pymongo_collection().find_one(
            {
                "$or": [
                    {"source_user_id": user_id},
                    {"target_user_id": user_id},
                ],
                "status": {
                    "$in": [
                        AccountMergeStatus.PREPARED,
                        AccountMergeStatus.MIGRATING,
                        AccountMergeStatus.MONGO_COMPLETE,
                    ]
                },
            },
            {"_id": 1},
        )
        if merge is not None:
            raise AccountOperationConflict()
        collection = AccountDeletionDocument.get_pymongo_collection()
        existing = await collection.find_one(
            {
                "user_id": user_id,
                "status": {"$ne": AccountDeletionStatus.CANCELLED},
            }
        )
        if existing is not None:
            document = AccountDeletionDocument.model_validate(existing)
            await self.ensure_fence(document, now)
            return document
        cancelled = await collection.find_one(
            {"user_id": user_id, "status": AccountDeletionStatus.CANCELLED},
            {"_id": 1},
        )
        if cancelled is not None:
            raw = await collection.find_one_and_update(
                {
                    "_id": cancelled["_id"],
                    "status": AccountDeletionStatus.CANCELLED,
                },
                {
                    "$set": {
                        "telescan_id": getattr(user, "telescan_id"),
                        "photo_url": getattr(user, "photo_s3_link", None),
                        "status": AccountDeletionStatus.PREPARED,
                        "cleanup_attempts": 0,
                        "created_at": now,
                        "updated_at": now,
                        "completed_at": None,
                        "retention_until": None,
                    }
                },
                return_document=ReturnDocument.AFTER,
            )
            if raw is None:
                raise AccountOperationConflict()
            document = AccountDeletionDocument.model_validate(raw)
            await self._after_journal_hook()
            await self.ensure_fence(document, now)
            return document

        durable_journal_id = (
            PydanticObjectId(journal_id) if journal_id else PydanticObjectId()
        )
        try:
            await collection.insert_one(
                {
                    "_id": durable_journal_id,
                    "user_id": user_id,
                    "telescan_id": getattr(user, "telescan_id"),
                    "photo_url": getattr(user, "photo_s3_link", None),
                    "status": AccountDeletionStatus.PREPARED,
                    "cleanup_attempts": 0,
                    "created_at": now,
                    "updated_at": now,
                    "completed_at": None,
                    "retention_until": None,
                }
            )
        except Exception:
            concurrent = await collection.find_one(
                {
                    "user_id": user_id,
                    "status": {"$ne": AccountDeletionStatus.CANCELLED},
                }
            )
            if concurrent is None:
                raise
            document = AccountDeletionDocument.model_validate(concurrent)
            await self.ensure_fence(document, now)
            return document
        raw = await collection.find_one({"_id": durable_journal_id})
        if raw is None:
            raise LookupError("deletion journal disappeared after insert")
        document = AccountDeletionDocument.model_validate(raw)
        await self._after_journal_hook()
        await self.ensure_fence(document, now)
        return document

    async def _after_journal_hook(self) -> None:
        if self._after_journal_persisted is not None:
            await self._after_journal_persisted()

    async def advance(
        self, deletion: AccountDeletionDocument, now: datetime
    ) -> AccountDeletionDocument:
        user_id = deletion.user_id
        await self.ensure_fence(deletion, now)
        if deletion.id is None:
            raise LookupError("deletion journal is not persisted")
        # Revocation is deliberately the first irreversible domain operation.
        await self._sweep_user_state(user_id, now)
        await AppleIdentityDocument.get_pymongo_collection().delete_many(
            {"user_id": user_id}
        )
        await DeviceSessionDocument.get_pymongo_collection().delete_many(
            {"user_id": user_id}
        )
        await UserDocument.get_pymongo_collection().delete_one({"_id": user_id})
        # A final idempotent sweep makes terminal completion contingent on zero
        # references, including writes resumed after their initial auth check.
        await self._sweep_user_state(user_id, now)
        if await self._user_reference_count(user_id):
            raise AccountOperationConflict()
        if self._before_terminal is not None:
            await self._before_terminal()

        deletion_id = deletion.id
        if deletion_id is None:
            raise LookupError("deletion journal is not persisted")
        raw = (
            await AccountDeletionDocument.get_pymongo_collection().find_one_and_update(
                {"_id": deletion_id, "status": AccountDeletionStatus.PREPARED},
                {
                    "$set": {
                        "status": AccountDeletionStatus.DB_COMPLETE,
                        "updated_at": now,
                    }
                },
                return_document=ReturnDocument.AFTER,
            )
        )
        if raw is None:
            raw = await AccountDeletionDocument.get_pymongo_collection().find_one(
                {"_id": deletion_id}
            )
        if raw is None:
            raise LookupError("deletion journal disappeared")
        return AccountDeletionDocument.model_validate(raw)

    async def ensure_fence(
        self, deletion: AccountDeletionDocument, now: datetime
    ) -> None:
        if deletion.id is None:
            raise LookupError("deletion journal is not persisted")
        await self._fences.install(
            str(deletion.user_id), "deletion", str(deletion.id), now
        )

    async def _sweep_user_state(self, user_id: PydanticObjectId, now: datetime) -> None:
        await DeviceSessionDocument.get_pymongo_collection().update_many(
            {"user_id": user_id, "revoked_at": None},
            {"$set": {"revoked_at": now}},
        )
        await LinkCodeDocument.get_pymongo_collection().delete_many(
            {"user_id": user_id}
        )
        await ReviewCodeDocument.get_pymongo_collection().delete_many(
            {"user_id": user_id}
        )
        await ConfirmationRequestDocument.get_pymongo_collection().delete_many(
            {"user_id": user_id}
        )
        await BlockDocument.get_pymongo_collection().delete_many(
            {"$or": [{"blocker_id": user_id}, {"blocked_id": user_id}]}
        )
        reports = ReportDocument.get_pymongo_collection()
        await reports.update_many(
            {"reporter_id": user_id},
            {"$set": {"reporter_id": None, "reporter_telescan_id": None}},
        )
        await reports.update_many({"target_id": user_id}, {"$set": {"target_id": None}})
        await DeviceSessionDocument.get_pymongo_collection().delete_many(
            {"user_id": user_id}
        )

    async def _user_reference_count(self, user_id: PydanticObjectId) -> int:
        counts = [
            await UserDocument.get_pymongo_collection().count_documents(
                {"_id": user_id}
            ),
            await AppleIdentityDocument.get_pymongo_collection().count_documents(
                {"user_id": user_id}
            ),
            await DeviceSessionDocument.get_pymongo_collection().count_documents(
                {"user_id": user_id}
            ),
            await BlockDocument.get_pymongo_collection().count_documents(
                {"$or": [{"blocker_id": user_id}, {"blocked_id": user_id}]}
            ),
            await ReportDocument.get_pymongo_collection().count_documents(
                {"$or": [{"reporter_id": user_id}, {"target_id": user_id}]}
            ),
            await LinkCodeDocument.get_pymongo_collection().count_documents(
                {"user_id": user_id}
            ),
            await ReviewCodeDocument.get_pymongo_collection().count_documents(
                {"user_id": user_id}
            ),
            await ConfirmationRequestDocument.get_pymongo_collection().count_documents(
                {"user_id": user_id}
            ),
        ]
        return sum(counts)

    async def list_incomplete(self, limit: int) -> list[AccountDeletionDocument]:
        cursor = (
            AccountDeletionDocument.get_pymongo_collection()
            .find(
                {
                    "status": {
                        "$in": [
                            AccountDeletionStatus.PREPARED,
                            AccountDeletionStatus.DB_COMPLETE,
                        ]
                    }
                }
            )
            .sort("updated_at", 1)
            .limit(limit)
        )
        return [AccountDeletionDocument.model_validate(raw) async for raw in cursor]

    async def mark_cleanup_completed(self, deletion_id: str, now: datetime) -> None:
        if not PydanticObjectId.is_valid(deletion_id):
            return
        retention_until = now + timedelta(days=30)
        collection = AccountDeletionDocument.get_pymongo_collection()
        journal = await collection.find_one({"_id": PydanticObjectId(deletion_id)})
        if journal is None:
            return
        await self._fences.mark_completed(
            str(journal["user_id"]),
            "deletion",
            deletion_id,
            retention_until,
            now,
        )
        await collection.update_one(
            {"_id": PydanticObjectId(deletion_id)},
            {
                "$set": {
                    "status": AccountDeletionStatus.COMPLETED,
                    "completed_at": now,
                    "updated_at": now,
                    "retention_until": retention_until,
                }
            },
        )

    async def record_cleanup_attempt(self, deletion_id: str, now: datetime) -> None:
        if not PydanticObjectId.is_valid(deletion_id):
            return
        await AccountDeletionDocument.get_pymongo_collection().update_one(
            {"_id": PydanticObjectId(deletion_id)},
            {"$inc": {"cleanup_attempts": 1}, "$set": {"updated_at": now}},
        )
