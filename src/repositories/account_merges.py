from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from beanie import PydanticObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from src.domain.enums import (
    AccountDeletionStatus,
    AccountMergeStatus,
    ConfirmationStatus,
    LinkCodeStatus,
)
from src.domain.errors import (
    AccountOperationConflict,
    AppleIdentityConflict,
    TelegramIdentityConflict,
)
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


class AccountMergeRepository:
    """Durable, idempotent Mongo portion of Apple-to-Telegram adoption.

    Production currently uses standalone MongoDB, so cross-collection
    transactions are unavailable. Each operation below is repeatable and the
    journal remains authoritative until storage cleanup completes.
    """

    def __init__(
        self,
        fences: AccountOperationFenceRepositoryPort,
        after_journal_persisted: Callable[[], Awaitable[None]] | None = None,
        before_terminal: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._fences = fences
        self._after_journal_persisted = after_journal_persisted
        self._before_terminal = before_terminal

    async def get_by_source(self, source_user_id: str) -> AccountMergeDocument | None:
        if not PydanticObjectId.is_valid(source_user_id):
            return None
        raw = await AccountMergeDocument.get_pymongo_collection().find_one(
            {
                "source_user_id": PydanticObjectId(source_user_id),
                "status": {"$ne": AccountMergeStatus.CANCELLED},
            }
        )
        return AccountMergeDocument.model_validate(raw) if raw else None

    async def has_active_for_user(self, user_id: str) -> bool:
        if not PydanticObjectId.is_valid(user_id):
            return False
        object_id = PydanticObjectId(user_id)
        raw = await AccountMergeDocument.get_pymongo_collection().find_one(
            {
                "$or": [
                    {
                        "source_user_id": object_id,
                        "status": {
                            "$in": [
                                AccountMergeStatus.PREPARED,
                                AccountMergeStatus.MIGRATING,
                                AccountMergeStatus.MONGO_COMPLETE,
                                AccountMergeStatus.COMPLETED,
                            ]
                        },
                    },
                    {
                        "target_user_id": object_id,
                        "status": {
                            "$in": [
                                AccountMergeStatus.PREPARED,
                                AccountMergeStatus.MIGRATING,
                            ]
                        },
                    },
                ],
            },
            {"_id": 1},
        )
        return raw is not None

    async def prepare(
        self,
        source_user: Any,
        target_user: Any,
        apple_subject: str,
        code_hash: str,
        code_kind: str,
        device_id: UUID,
        now: datetime,
        journal_id: str | None = None,
    ) -> AccountMergeDocument:
        source_id = PydanticObjectId(str(getattr(source_user, "id")))
        target_id = PydanticObjectId(str(getattr(target_user, "id")))
        if source_id == target_id:
            raise AccountOperationConflict()
        deletion = await AccountDeletionDocument.get_pymongo_collection().find_one(
            {
                "user_id": {"$in": [source_id, target_id]},
                "status": {
                    "$in": [
                        AccountDeletionStatus.PREPARED,
                        AccountDeletionStatus.DB_COMPLETE,
                    ]
                },
            },
            {"_id": 1},
        )
        if deletion is not None:
            raise AccountOperationConflict()
        collection = AccountMergeDocument.get_pymongo_collection()
        existing = await collection.find_one(
            {
                "source_user_id": source_id,
                "status": {"$ne": AccountMergeStatus.CANCELLED},
            }
        )
        if existing is not None:
            document = AccountMergeDocument.model_validate(existing)
            self._validate_prepared_merge(
                document,
                target_id,
                apple_subject,
                code_hash,
                code_kind,
                device_id,
            )
            await self.ensure_fences(document, now)
            return document
        cancelled = await collection.find_one(
            {
                "source_user_id": source_id,
                "status": AccountMergeStatus.CANCELLED,
            },
            {"_id": 1},
        )
        if cancelled is not None:
            raw = await collection.find_one_and_update(
                {
                    "_id": cancelled["_id"],
                    "status": AccountMergeStatus.CANCELLED,
                },
                {
                    "$set": {
                        "target_user_id": target_id,
                        "apple_subject": apple_subject,
                        "source_telescan_id": getattr(source_user, "telescan_id"),
                        "source_photo_url": getattr(source_user, "photo_s3_link", None),
                        "source_session_ids": [],
                        "authorization_code_hash": code_hash,
                        "authorization_code_kind": code_kind,
                        "authorization_device_id": device_id,
                        "authorized_at": None,
                        "status": AccountMergeStatus.PREPARED,
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
            document = AccountMergeDocument.model_validate(raw)
            await self._after_journal_hook()
            await self.ensure_fences(document, now)
            return document

        durable_journal_id = (
            PydanticObjectId(journal_id) if journal_id else PydanticObjectId()
        )
        try:
            await collection.insert_one(
                {
                    "_id": durable_journal_id,
                    "source_user_id": source_id,
                    "target_user_id": target_id,
                    "apple_subject": apple_subject,
                    "source_telescan_id": getattr(source_user, "telescan_id"),
                    "source_photo_url": getattr(source_user, "photo_s3_link", None),
                    "source_session_ids": [],
                    "authorization_code_hash": code_hash,
                    "authorization_code_kind": code_kind,
                    "authorization_device_id": device_id,
                    "authorized_at": None,
                    "status": AccountMergeStatus.PREPARED,
                    "cleanup_attempts": 0,
                    "created_at": now,
                    "updated_at": now,
                    "completed_at": None,
                    "retention_until": None,
                }
            )
        except Exception as error:
            if isinstance(error, DuplicateKeyError):
                concurrent = await collection.find_one(
                    {
                        "source_user_id": source_id,
                        "status": {"$ne": AccountMergeStatus.CANCELLED},
                    }
                )
                if concurrent is None:
                    raise TelegramIdentityConflict() from error
                document = AccountMergeDocument.model_validate(concurrent)
                self._validate_prepared_merge(
                    document,
                    target_id,
                    apple_subject,
                    code_hash,
                    code_kind,
                    device_id,
                )
                await self.ensure_fences(document, now)
                return document
            raise
        raw = await collection.find_one({"_id": durable_journal_id})
        if raw is None:
            raise LookupError("merge journal disappeared after insert")
        document = AccountMergeDocument.model_validate(raw)
        await self._after_journal_hook()
        await self.ensure_fences(document, now)
        return document

    async def _after_journal_hook(self) -> None:
        if self._after_journal_persisted is not None:
            await self._after_journal_persisted()

    @staticmethod
    def _validate_prepared_merge(
        document: AccountMergeDocument,
        target_id: PydanticObjectId,
        apple_subject: str,
        code_hash: str,
        code_kind: str,
        device_id: UUID,
    ) -> None:
        proof_matches = document.authorized_at is not None or (
            document.authorization_code_hash == code_hash
            and document.authorization_code_kind == code_kind
            and document.authorization_device_id == device_id
        )
        if (
            document.target_user_id != target_id
            or document.apple_subject != apple_subject
            or not proof_matches
        ):
            raise TelegramIdentityConflict()

    async def authorize(
        self, merge: AccountMergeDocument, now: datetime
    ) -> AccountMergeDocument:
        if merge.id is None:
            raise LookupError("merge journal is not persisted")
        raw = await AccountMergeDocument.get_pymongo_collection().find_one_and_update(
            {
                "_id": merge.id,
                "status": {
                    "$in": [
                        AccountMergeStatus.PREPARED,
                        AccountMergeStatus.MIGRATING,
                    ]
                },
            },
            {
                "$set": {
                    "authorized_at": now,
                    "authorization_code_hash": None,
                    "authorization_code_kind": None,
                    "authorization_device_id": None,
                    "updated_at": now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if raw is None:
            raise AccountOperationConflict()
        return AccountMergeDocument.model_validate(raw)

    async def reconcile_authorization(
        self, merge: AccountMergeDocument, now: datetime
    ) -> bool:
        if merge.authorized_at is not None:
            return True
        if (
            merge.authorization_code_hash is None
            or merge.authorization_code_kind is None
            or merge.authorization_device_id is None
        ):
            raise AccountOperationConflict()
        if merge.authorization_code_kind == "review":
            collection = ReviewCodeDocument.get_pymongo_collection()
        elif merge.authorization_code_kind == "link":
            collection = LinkCodeDocument.get_pymongo_collection()
        else:
            raise AccountOperationConflict()
        code = await collection.find_one(
            {"code_hash": merge.authorization_code_hash},
            {
                "status": 1,
                "expires_at": 1,
                "retention_until": 1,
                "consumed_by_device_id": 1,
            },
        )
        proof_deadline = (
            code.get("retention_until")
            if code is not None and merge.authorization_code_kind == "review"
            else code.get("expires_at")
            if code is not None
            else None
        )
        if (
            code is not None
            and code.get("status") == LinkCodeStatus.CONSUMED
            and code.get("consumed_by_device_id") == merge.authorization_device_id
            and proof_deadline is not None
            and proof_deadline > now
        ):
            await self.authorize(merge, now)
            return True
        if (
            code is not None
            and code.get("status") == LinkCodeStatus.ISSUED
            and code.get("expires_at") is not None
            and code["expires_at"] > now
        ):
            return False
        if merge.id is not None:
            operation_id = str(merge.id)
            # Reopen both durable gates first. If the process stops between
            # either release or the journal CAS, PREPARED remains resumable and
            # reconciliation retries the idempotent releases.
            await self._fences.release_operation(
                str(merge.source_user_id), "merge", operation_id
            )
            await self._fences.release_operation(
                str(merge.target_user_id), "merge", operation_id
            )
            await AccountMergeDocument.get_pymongo_collection().update_one(
                {
                    "_id": merge.id,
                    "status": AccountMergeStatus.PREPARED,
                    "authorized_at": None,
                },
                {
                    "$set": {
                        "status": AccountMergeStatus.CANCELLED,
                        "updated_at": now,
                        "completed_at": now,
                        "retention_until": now + timedelta(days=30),
                    }
                },
            )
        return False

    async def migrate(
        self, merge: AccountMergeDocument, now: datetime
    ) -> AccountMergeDocument:
        source_id = merge.source_user_id
        merge_id = merge.id
        if merge_id is None:
            raise LookupError("merge journal is not persisted")
        if merge.authorized_at is None:
            raise AccountOperationConflict()
        journals = AccountMergeDocument.get_pymongo_collection()
        await journals.update_one(
            {"_id": merge_id},
            {
                "$set": {
                    "status": AccountMergeStatus.MIGRATING,
                    "updated_at": now,
                }
            },
        )
        await self.ensure_fences(merge, now)

        # AccountMergeService holds both in-process account locks from before
        # fence installation through this sweep. With the production
        # single-process invariant, no admitted writer can cross this point.
        await self._migrate_source_state(merge, now)
        if await self._source_reference_count(source_id):
            raise AccountOperationConflict()
        if self._before_terminal is not None:
            await self._before_terminal()
        # Admission for both users remains closed, so the zero-reference result
        # cannot be invalidated between the check and terminal CAS.
        raw = await journals.find_one_and_update(
            {"_id": merge_id, "status": AccountMergeStatus.MIGRATING},
            {
                "$set": {
                    "status": AccountMergeStatus.MONGO_COMPLETE,
                    "updated_at": now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if raw is None:
            raw = await journals.find_one({"_id": merge_id})
        if raw is None:
            raise LookupError("merge journal disappeared")
        return AccountMergeDocument.model_validate(raw)

    async def ensure_fences(self, merge: AccountMergeDocument, now: datetime) -> None:
        if merge.id is None:
            raise LookupError("merge journal is not persisted")
        await self._install_fence_ids(
            merge.source_user_id, merge.target_user_id, merge.id, now
        )

    async def _install_fence_ids(
        self,
        source_id: PydanticObjectId,
        target_id: PydanticObjectId,
        operation_id: PydanticObjectId,
        now: datetime,
    ) -> None:
        # Never compensate a partial reaffirmation by opening an already
        # durable fence. The PREPARED journal is authoritative and startup or
        # runtime reconciliation will idempotently install any missing side.
        for user_id in sorted({str(source_id), str(target_id)}):
            await self._fences.install(user_id, "merge", str(operation_id), now)

    async def _migrate_source_state(
        self, merge: AccountMergeDocument, now: datetime
    ) -> None:
        source_id = merge.source_user_id
        target_id = merge.target_user_id
        merge_id = merge.id
        if merge_id is None:
            raise LookupError("merge journal is not persisted")
        await self._migrate_blocks(source_id, target_id)
        await self._migrate_reports(source_id, target_id)
        await self._cancel_transient_state(source_id, now)

        sessions = DeviceSessionDocument.get_pymongo_collection()
        discovered = [
            item
            async for item in sessions.find(
                {"user_id": source_id}, {"_id": 1, "device_id": 1}
            )
        ]
        discovered_ids = [item["_id"] for item in discovered]
        journals = AccountMergeDocument.get_pymongo_collection()
        if discovered_ids:
            await journals.update_one(
                {"_id": merge_id},
                {
                    "$addToSet": {"source_session_ids": {"$each": discovered_ids}},
                    "$set": {"updated_at": now},
                },
            )
        await self._move_identity(merge.apple_subject, source_id, target_id, now)
        for source_session in discovered:
            # Preserve non-conflicting canonical sessions. Only the canonical
            # session for the same device is replaced by the authenticated
            # placeholder session being adopted.
            await sessions.delete_many(
                {
                    "user_id": target_id,
                    "device_id": source_session["device_id"],
                    "_id": {"$ne": source_session["_id"]},
                }
            )
            await sessions.update_one(
                {"_id": source_session["_id"], "user_id": source_id},
                {"$set": {"user_id": target_id}},
            )

    async def _source_reference_count(self, source_id: PydanticObjectId) -> int:
        counts = [
            await DeviceSessionDocument.get_pymongo_collection().count_documents(
                {"user_id": source_id}
            ),
            await BlockDocument.get_pymongo_collection().count_documents(
                {"$or": [{"blocker_id": source_id}, {"blocked_id": source_id}]}
            ),
            await ReportDocument.get_pymongo_collection().count_documents(
                {"$or": [{"reporter_id": source_id}, {"target_id": source_id}]}
            ),
            await LinkCodeDocument.get_pymongo_collection().count_documents(
                {"user_id": source_id, "status": LinkCodeStatus.ISSUED}
            ),
            await ReviewCodeDocument.get_pymongo_collection().count_documents(
                {"user_id": source_id, "status": LinkCodeStatus.ISSUED}
            ),
            await ConfirmationRequestDocument.get_pymongo_collection().count_documents(
                {"user_id": source_id, "status": ConfirmationStatus.PENDING}
            ),
        ]
        return sum(counts)

    async def list_cleanup_pending(self, limit: int) -> list[AccountMergeDocument]:
        cursor = (
            AccountMergeDocument.get_pymongo_collection()
            .find({"status": AccountMergeStatus.MONGO_COMPLETE})
            .sort("updated_at", 1)
            .limit(limit)
        )
        return [AccountMergeDocument.model_validate(raw) async for raw in cursor]

    async def list_incomplete(self, limit: int) -> list[AccountMergeDocument]:
        cursor = (
            AccountMergeDocument.get_pymongo_collection()
            .find(
                {
                    "status": {
                        "$in": [
                            AccountMergeStatus.PREPARED,
                            AccountMergeStatus.MIGRATING,
                            AccountMergeStatus.MONGO_COMPLETE,
                        ]
                    }
                }
            )
            .sort("updated_at", 1)
            .limit(limit)
        )
        return [AccountMergeDocument.model_validate(raw) async for raw in cursor]

    async def mark_cleanup_completed(self, merge_id: str, now: datetime) -> None:
        if not PydanticObjectId.is_valid(merge_id):
            return
        retention_until = now + timedelta(days=30)
        collection = AccountMergeDocument.get_pymongo_collection()
        journal = await collection.find_one({"_id": PydanticObjectId(merge_id)})
        if journal is None:
            return
        # Complete the durable fence outbox first. If this write fails, the
        # journal remains MONGO_COMPLETE and is retried by reconciliation. If
        # the following journal CAS fails, repeating this fence update is safe.
        await self._fences.mark_completed(
            str(journal["source_user_id"]),
            "merge",
            merge_id,
            retention_until,
            now,
        )
        await collection.update_one(
            {"_id": PydanticObjectId(merge_id)},
            {
                "$set": {
                    "status": AccountMergeStatus.COMPLETED,
                    "completed_at": now,
                    "updated_at": now,
                    "retention_until": retention_until,
                }
            },
        )

    async def release_target_fence(self, merge_id: str, target_user_id: str) -> None:
        await self._fences.release_operation(target_user_id, "merge", merge_id)

    async def record_cleanup_attempt(self, merge_id: str, now: datetime) -> None:
        if not PydanticObjectId.is_valid(merge_id):
            return
        await AccountMergeDocument.get_pymongo_collection().update_one(
            {"_id": PydanticObjectId(merge_id)},
            {"$inc": {"cleanup_attempts": 1}, "$set": {"updated_at": now}},
        )

    async def _migrate_blocks(
        self, source_id: PydanticObjectId, target_id: PydanticObjectId
    ) -> None:
        collection = BlockDocument.get_pymongo_collection()
        target = await UserDocument.get_pymongo_collection().find_one(
            {"_id": target_id}
        )
        if target is None:
            raise LookupError(str(target_id))
        cursor = collection.find(
            {"$or": [{"blocker_id": source_id}, {"blocked_id": source_id}]}
        )
        async for block in cursor:
            blocker_id = (
                target_id if block["blocker_id"] == source_id else block["blocker_id"]
            )
            blocked_id = (
                target_id if block["blocked_id"] == source_id else block["blocked_id"]
            )
            if blocker_id == blocked_id:
                await collection.delete_one({"_id": block["_id"]})
                continue
            update: dict[str, object] = {
                "blocker_id": blocker_id,
                "blocked_id": blocked_id,
            }
            if block["blocked_id"] == source_id:
                update.update(
                    {
                        "blocked_telescan_id": target["telescan_id"],
                        "blocked_name": target.get("tg_name"),
                        "blocked_username": target.get("tg_username"),
                        "blocked_photo_url": target.get("photo_s3_link"),
                    }
                )
            try:
                await collection.update_one({"_id": block["_id"]}, {"$set": update})
            except DuplicateKeyError:
                await collection.delete_one({"_id": block["_id"]})

    async def _migrate_reports(
        self, source_id: PydanticObjectId, target_id: PydanticObjectId
    ) -> None:
        users = UserDocument.get_pymongo_collection()
        target = await users.find_one({"_id": target_id})
        if target is None:
            raise LookupError(str(target_id))
        collection = ReportDocument.get_pymongo_collection()
        cursor = collection.find({"reporter_id": source_id})
        async for report in cursor:
            try:
                await collection.update_one(
                    {"_id": report["_id"], "reporter_id": source_id},
                    {
                        "$set": {
                            "reporter_id": target_id,
                            "reporter_telescan_id": target["telescan_id"],
                        }
                    },
                )
            except DuplicateKeyError:
                # Preserve the moderation record while removing the conflicting
                # idempotency relation; the canonical target record wins.
                await collection.update_one(
                    {"_id": report["_id"]},
                    {
                        "$set": {
                            "reporter_id": None,
                            "reporter_telescan_id": None,
                        }
                    },
                )
        await collection.update_many(
            {"target_id": source_id},
            {
                "$set": {
                    "target_id": target_id,
                    "target_telescan_id": target["telescan_id"],
                }
            },
        )

    async def _cancel_transient_state(
        self, source_id: PydanticObjectId, now: datetime
    ) -> None:
        await LinkCodeDocument.get_pymongo_collection().update_many(
            {"user_id": source_id, "status": LinkCodeStatus.ISSUED},
            {
                "$set": {"status": LinkCodeStatus.REVOKED},
                "$max": {"expires_at": now},
            },
        )
        await ReviewCodeDocument.get_pymongo_collection().update_many(
            {"user_id": source_id, "status": LinkCodeStatus.ISSUED},
            {
                "$set": {
                    "status": LinkCodeStatus.REVOKED,
                    "revoked_at": now,
                    "revoked_by": "account-merge",
                }
            },
        )
        await ConfirmationRequestDocument.get_pymongo_collection().update_many(
            {"user_id": source_id, "status": ConfirmationStatus.PENDING},
            {"$set": {"status": ConfirmationStatus.CANCELLED}},
        )

    async def _move_identity(
        self,
        subject: str,
        source_id: PydanticObjectId,
        target_id: PydanticObjectId,
        now: datetime,
    ) -> None:
        collection = AppleIdentityDocument.get_pymongo_collection()
        target_identity = await collection.find_one({"user_id": target_id})
        if target_identity is not None:
            if target_identity.get("subject") != subject:
                raise TelegramIdentityConflict()
            return
        try:
            result = await collection.update_one(
                {"subject": subject, "user_id": source_id},
                {"$set": {"user_id": target_id, "updated_at": now}},
            )
        except DuplicateKeyError as error:
            raise TelegramIdentityConflict() from error
        if result.modified_count != 1:
            raise AppleIdentityConflict()
