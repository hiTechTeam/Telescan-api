from datetime import datetime
from typing import Any
from uuid import UUID

from beanie import PydanticObjectId
from pymongo import DESCENDING, ReturnDocument

from src.infrastructure.mongodb.documents import BlockDocument


class BlockRepository:
    async def create(
        self,
        blocker_id: str,
        target: Any,
        now: datetime,
    ) -> BlockDocument:
        raw = await BlockDocument.get_pymongo_collection().find_one_and_update(
            {
                "blocker_id": PydanticObjectId(blocker_id),
                "blocked_id": PydanticObjectId(str(getattr(target, "id"))),
            },
            {
                "$setOnInsert": {
                    "blocked_telescan_id": getattr(target, "telescan_id"),
                    "blocked_name": getattr(target, "tg_name", None),
                    "blocked_username": getattr(target, "tg_username", None),
                    "blocked_photo_url": getattr(target, "photo_s3_link", None),
                    "created_at": now,
                }
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return BlockDocument.model_validate(raw)

    async def delete(self, blocker_id: str, blocked_telescan_id: UUID) -> bool:
        result = await BlockDocument.get_pymongo_collection().delete_one(
            {
                "blocker_id": PydanticObjectId(blocker_id),
                "blocked_telescan_id": blocked_telescan_id,
            }
        )
        return result.deleted_count == 1

    async def exists_between(self, first_user_id: str, second_user_id: str) -> bool:
        first = PydanticObjectId(first_user_id)
        second = PydanticObjectId(second_user_id)
        document = await BlockDocument.get_pymongo_collection().find_one(
            {
                "$or": [
                    {"blocker_id": first, "blocked_id": second},
                    {"blocker_id": second, "blocked_id": first},
                ]
            },
            {"_id": 1},
        )
        return document is not None

    async def list_for_user(self, blocker_id: str) -> list[BlockDocument]:
        cursor = (
            BlockDocument.get_pymongo_collection()
            .find({"blocker_id": PydanticObjectId(blocker_id)})
            .sort("created_at", DESCENDING)
        )
        return [BlockDocument.model_validate(raw) async for raw in cursor]

    async def delete_for_user(self, user_id: str) -> None:
        object_id = PydanticObjectId(user_id)
        await BlockDocument.get_pymongo_collection().delete_many(
            {"$or": [{"blocker_id": object_id}, {"blocked_id": object_id}]}
        )
