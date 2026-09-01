from datetime import UTC, datetime

from beanie import PydanticObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from src.domain.errors import AccountOperationConflict
from src.infrastructure.mongodb.documents import AccountOperationFenceDocument


class AccountOperationFenceRepository:
    """Durable fail-closed admission state for account sagas.

    Live mutation serialization belongs to ``AccountOperationGuard``. This
    collection intentionally contains no expiring writer leases: after a
    process crash there are no surviving writers, while an incomplete journal
    can reinstall its fence before the API starts serving.
    """

    async def install(
        self,
        user_id: str,
        operation_kind: str,
        operation_id: str,
        now: datetime,
    ) -> None:
        if not PydanticObjectId.is_valid(user_id) or not PydanticObjectId.is_valid(
            operation_id
        ):
            raise AccountOperationConflict()
        user_object_id = PydanticObjectId(user_id)
        operation_object_id = PydanticObjectId(operation_id)
        try:
            raw = await AccountOperationFenceDocument.get_pymongo_collection().find_one_and_update(
                {
                    "user_id": user_object_id,
                    "$or": [
                        {"fenced": {"$ne": True}},
                        {
                            "operation_kind": operation_kind,
                            "operation_id": operation_object_id,
                        },
                    ],
                },
                {
                    "$set": {
                        "fenced": True,
                        "operation_kind": operation_kind,
                        "operation_id": operation_object_id,
                        "updated_at": now,
                        "retention_until": None,
                    },
                    "$setOnInsert": {"created_at": now},
                    "$unset": {"active_mutations": "", "leases": ""},
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError as error:
            raise AccountOperationConflict() from error
        if raw is None:
            raise AccountOperationConflict()

    async def release_operation(
        self,
        user_id: str,
        operation_kind: str,
        operation_id: str,
    ) -> None:
        if not PydanticObjectId.is_valid(user_id) or not PydanticObjectId.is_valid(
            operation_id
        ):
            return
        await AccountOperationFenceDocument.get_pymongo_collection().update_one(
            {
                "user_id": PydanticObjectId(user_id),
                "fenced": True,
                "operation_kind": operation_kind,
                "operation_id": PydanticObjectId(operation_id),
            },
            {
                "$set": {
                    "fenced": False,
                    "operation_kind": None,
                    "operation_id": None,
                    "retention_until": None,
                    "updated_at": datetime.now(UTC),
                }
            },
        )

    async def mark_completed(
        self,
        user_id: str,
        operation_kind: str,
        operation_id: str,
        retention_until: datetime,
        now: datetime,
    ) -> None:
        if not PydanticObjectId.is_valid(user_id) or not PydanticObjectId.is_valid(
            operation_id
        ):
            return
        result = (
            await AccountOperationFenceDocument.get_pymongo_collection().update_one(
                {
                    "user_id": PydanticObjectId(user_id),
                    "fenced": True,
                    "operation_kind": operation_kind,
                    "operation_id": PydanticObjectId(operation_id),
                },
                {"$set": {"retention_until": retention_until, "updated_at": now}},
            )
        )
        if result.matched_count != 1:
            raise AccountOperationConflict()

    async def is_fenced(self, user_id: str) -> bool:
        if not PydanticObjectId.is_valid(user_id):
            return False
        raw = await AccountOperationFenceDocument.get_pymongo_collection().find_one(
            {"user_id": PydanticObjectId(user_id), "fenced": True},
            {"_id": 1},
        )
        return raw is not None


__all__ = ["AccountOperationFenceRepository"]
