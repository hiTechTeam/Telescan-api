from datetime import datetime
from uuid import UUID

from beanie import PydanticObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from src.domain.enums import LinkCodeStatus
from src.domain.errors import LinkCodeCollision
from src.infrastructure.mongodb.documents import LinkCodeDocument


class LinkCodeRepository:
    async def revoke_issued(self, user_id: str, now: datetime) -> None:
        await LinkCodeDocument.get_pymongo_collection().update_many(
            {"user_id": PydanticObjectId(user_id), "status": LinkCodeStatus.ISSUED},
            {"$set": {"status": LinkCodeStatus.REVOKED}, "$max": {"expires_at": now}},
        )

    async def create(
        self,
        code_hash: str,
        user_id: str,
        now: datetime,
        expires_at: datetime,
    ) -> LinkCodeDocument:
        document = LinkCodeDocument(
            code_hash=code_hash,
            user_id=PydanticObjectId(user_id),
            created_at=now,
            expires_at=expires_at,
        )
        try:
            await document.insert()
        except DuplicateKeyError as error:
            raise LinkCodeCollision() from error
        return document

    async def consume(
        self,
        code_hash: str,
        device_id: UUID,
        now: datetime,
    ) -> LinkCodeDocument | None:
        raw = await LinkCodeDocument.get_pymongo_collection().find_one_and_update(
            {
                "code_hash": code_hash,
                "status": LinkCodeStatus.ISSUED,
                "expires_at": {"$gt": now},
            },
            {
                "$set": {
                    "status": LinkCodeStatus.CONSUMED,
                    "consumed_at": now,
                    "consumed_by_device_id": device_id,
                },
                "$inc": {"attempts": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        return LinkCodeDocument.model_validate(raw) if raw else None

    async def delete_for_user(self, user_id: str) -> None:
        await LinkCodeDocument.find(
            LinkCodeDocument.user_id == PydanticObjectId(user_id)
        ).delete()
