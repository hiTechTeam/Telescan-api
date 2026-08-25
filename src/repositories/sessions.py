from datetime import datetime
from uuid import UUID

from beanie import PydanticObjectId
from pymongo import ReturnDocument

from src.infrastructure.mongodb.documents import DeviceSessionDocument


class SessionRepository:
    async def create_or_replace(
        self,
        user_id: str,
        device_id: UUID,
        now: datetime,
        expires_at: datetime,
    ) -> DeviceSessionDocument:
        raw = await DeviceSessionDocument.get_pymongo_collection().find_one_and_update(
            {"user_id": PydanticObjectId(user_id), "device_id": device_id},
            {
                "$set": {
                    "refresh_token_hash": "",
                    "last_used_at": now,
                    "expires_at": expires_at,
                    "revoked_at": None,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return DeviceSessionDocument.model_validate(raw)

    async def set_refresh_hash(
        self, session_id: str, refresh_hash: str, now: datetime
    ) -> None:
        await DeviceSessionDocument.get_pymongo_collection().update_one(
            {"_id": PydanticObjectId(session_id), "revoked_at": None},
            {"$set": {"refresh_token_hash": refresh_hash, "last_used_at": now}},
        )

    async def get_active(
        self, session_id: str, now: datetime
    ) -> DeviceSessionDocument | None:
        if not PydanticObjectId.is_valid(session_id):
            return None
        return await DeviceSessionDocument.find_one(
            DeviceSessionDocument.id == PydanticObjectId(session_id),
            DeviceSessionDocument.revoked_at == None,  # noqa: E711
            DeviceSessionDocument.expires_at > now,
        )

    async def rotate_refresh_hash(
        self,
        session_id: str,
        expected_hash: str,
        new_hash: str,
        now: datetime,
    ) -> bool:
        result = await DeviceSessionDocument.get_pymongo_collection().update_one(
            {
                "_id": PydanticObjectId(session_id),
                "refresh_token_hash": expected_hash,
                "revoked_at": None,
                "expires_at": {"$gt": now},
            },
            {"$set": {"refresh_token_hash": new_hash, "last_used_at": now}},
        )
        return result.modified_count == 1

    async def revoke(self, session_id: str, now: datetime) -> None:
        if PydanticObjectId.is_valid(session_id):
            await DeviceSessionDocument.get_pymongo_collection().update_one(
                {"_id": PydanticObjectId(session_id), "revoked_at": None},
                {"$set": {"revoked_at": now}},
            )

    async def revoke_all(self, user_id: str, now: datetime) -> None:
        await DeviceSessionDocument.get_pymongo_collection().update_many(
            {"user_id": PydanticObjectId(user_id), "revoked_at": None},
            {"$set": {"revoked_at": now}},
        )

    async def move_to_user(
        self,
        session_id: str,
        current_user_id: str,
        target_user_id: str,
    ) -> DeviceSessionDocument:
        if not all(
            PydanticObjectId.is_valid(value)
            for value in (session_id, current_user_id, target_user_id)
        ):
            raise LookupError(session_id)
        collection = DeviceSessionDocument.get_pymongo_collection()
        current = await collection.find_one(
            {
                "_id": PydanticObjectId(session_id),
                "user_id": PydanticObjectId(current_user_id),
                "revoked_at": None,
            }
        )
        if current is None:
            raise LookupError(session_id)
        await collection.delete_many(
            {
                "user_id": PydanticObjectId(target_user_id),
                "device_id": current["device_id"],
                "_id": {"$ne": PydanticObjectId(session_id)},
            }
        )
        raw = await collection.find_one_and_update(
            {
                "_id": PydanticObjectId(session_id),
                "user_id": PydanticObjectId(current_user_id),
                "revoked_at": None,
            },
            {"$set": {"user_id": PydanticObjectId(target_user_id)}},
            return_document=ReturnDocument.AFTER,
        )
        if raw is None:
            raise LookupError(session_id)
        return DeviceSessionDocument.model_validate(raw)

    async def delete_for_user(self, user_id: str) -> None:
        await DeviceSessionDocument.find(
            DeviceSessionDocument.user_id == PydanticObjectId(user_id)
        ).delete()
