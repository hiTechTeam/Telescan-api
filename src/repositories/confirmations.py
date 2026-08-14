from datetime import datetime
from uuid import UUID

from beanie import PydanticObjectId
from pymongo import ReturnDocument

from src.domain.enums import ConfirmationAction, ConfirmationStatus
from src.infrastructure.mongodb.documents import ConfirmationRequestDocument


class ConfirmationRepository:
    async def create_logout_all(
        self, user_id: str, now: datetime, expires_at: datetime
    ) -> ConfirmationRequestDocument:
        await ConfirmationRequestDocument.get_pymongo_collection().update_many(
            {"user_id": PydanticObjectId(user_id), "status": ConfirmationStatus.PENDING},
            {"$set": {"status": ConfirmationStatus.CANCELLED}},
        )
        request = ConfirmationRequestDocument(
            user_id=PydanticObjectId(user_id),
            action=ConfirmationAction.LOGOUT_ALL,
            created_at=now,
            expires_at=expires_at,
        )
        await request.insert()
        return request

    async def register_message(
        self, confirmation_id: UUID, chat_id: int, message_id: int
    ) -> ConfirmationRequestDocument | None:
        raw = await ConfirmationRequestDocument.get_pymongo_collection().find_one_and_update(
            {"public_id": confirmation_id, "status": ConfirmationStatus.PENDING},
            {"$set": {"telegram_chat_id": chat_id, "telegram_message_id": message_id}},
            return_document=ReturnDocument.AFTER,
        )
        return ConfirmationRequestDocument.model_validate(raw) if raw else None

    async def decide(
        self,
        confirmation_id: UUID,
        user_id: str,
        status: ConfirmationStatus,
        now: datetime,
    ) -> ConfirmationRequestDocument | None:
        collection = ConfirmationRequestDocument.get_pymongo_collection()
        raw = await collection.find_one_and_update(
            {
                "public_id": confirmation_id,
                "user_id": PydanticObjectId(user_id),
                "status": ConfirmationStatus.PENDING,
                "expires_at": {"$gt": now},
            },
            {"$set": {"status": status}},
            return_document=ReturnDocument.AFTER,
        )
        if raw:
            return ConfirmationRequestDocument.model_validate(raw)

        expired = await collection.find_one_and_update(
            {
                "public_id": confirmation_id,
                "user_id": PydanticObjectId(user_id),
                "status": ConfirmationStatus.PENDING,
                "expires_at": {"$lte": now},
            },
            {"$set": {"status": ConfirmationStatus.EXPIRED}},
            return_document=ReturnDocument.AFTER,
        )
        if expired:
            return ConfirmationRequestDocument.model_validate(expired)
        existing = await ConfirmationRequestDocument.find_one(
            ConfirmationRequestDocument.public_id == confirmation_id,
            ConfirmationRequestDocument.user_id == PydanticObjectId(user_id),
        )
        return existing

    async def expire(
        self, confirmation_id: UUID, user_id: str, now: datetime
    ) -> ConfirmationRequestDocument | None:
        raw = await ConfirmationRequestDocument.get_pymongo_collection().find_one_and_update(
            {
                "public_id": confirmation_id,
                "user_id": PydanticObjectId(user_id),
                "status": ConfirmationStatus.PENDING,
                "expires_at": {"$lte": now},
            },
            {"$set": {"status": ConfirmationStatus.EXPIRED}},
            return_document=ReturnDocument.AFTER,
        )
        if raw:
            return ConfirmationRequestDocument.model_validate(raw)
        return await ConfirmationRequestDocument.find_one(
            ConfirmationRequestDocument.public_id == confirmation_id,
            ConfirmationRequestDocument.user_id == PydanticObjectId(user_id),
        )

    async def list_pending(self) -> list[ConfirmationRequestDocument]:
        return await ConfirmationRequestDocument.find(
            ConfirmationRequestDocument.status == ConfirmationStatus.PENDING
        ).to_list()

    async def delete_for_user(self, user_id: str) -> None:
        await ConfirmationRequestDocument.find(
            ConfirmationRequestDocument.user_id == PydanticObjectId(user_id)
        ).delete()
