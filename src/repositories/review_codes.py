import logging
from datetime import datetime
from uuid import UUID

from beanie import PydanticObjectId
from pymongo import ReturnDocument

from src.domain.enums import LinkCodeStatus
from src.infrastructure.mongodb.documents import ReviewCodeDocument


logger = logging.getLogger(__name__)


class ReviewCodeRepository:
    async def consume(
        self,
        code_hash: str,
        device_id: UUID,
        now: datetime,
    ) -> ReviewCodeDocument | None:
        raw = await ReviewCodeDocument.get_pymongo_collection().find_one_and_update(
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
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if raw is None:
            return None
        document = ReviewCodeDocument.model_validate(raw)
        logger.info(
            "Review code consumed review_code_id=%s batch_id=%s user_id=%s "
            "device_id=%s",
            document.public_id,
            document.batch_id,
            document.user_id,
            device_id,
        )
        return document

    async def delete_for_user(self, user_id: str) -> None:
        await ReviewCodeDocument.find(
            ReviewCodeDocument.user_id == PydanticObjectId(user_id)
        ).delete()
