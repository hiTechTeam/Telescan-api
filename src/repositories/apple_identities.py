from datetime import datetime

from beanie import PydanticObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from src.domain.errors import AppleIdentityConflict
from src.infrastructure.mongodb.documents import AppleIdentityDocument


class AppleIdentityRepository:
    async def get_by_subject(self, subject: str) -> AppleIdentityDocument | None:
        return await AppleIdentityDocument.find_one(
            AppleIdentityDocument.subject == subject
        )

    async def get_by_user_id(self, user_id: str) -> AppleIdentityDocument | None:
        if not PydanticObjectId.is_valid(user_id):
            return None
        return await AppleIdentityDocument.find_one(
            AppleIdentityDocument.user_id == PydanticObjectId(user_id)
        )

    async def create(
        self,
        subject: str,
        user_id: str,
        email: str | None,
        name: str | None,
        now: datetime,
    ) -> AppleIdentityDocument:
        identity = AppleIdentityDocument(
            subject=subject,
            user_id=PydanticObjectId(user_id),
            email=email,
            name=name,
            created_at=now,
            updated_at=now,
        )
        try:
            await identity.insert()
        except DuplicateKeyError as error:
            raise AppleIdentityConflict() from error
        return identity

    async def move_to_user(
        self,
        subject: str,
        current_user_id: str,
        target_user_id: str,
        now: datetime,
    ) -> AppleIdentityDocument:
        try:
            raw = await AppleIdentityDocument.get_pymongo_collection().find_one_and_update(
                {
                    "subject": subject,
                    "user_id": PydanticObjectId(current_user_id),
                },
                {
                    "$set": {
                        "user_id": PydanticObjectId(target_user_id),
                        "updated_at": now,
                    }
                },
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError as error:
            raise AppleIdentityConflict() from error
        if raw is None:
            raise AppleIdentityConflict()
        return AppleIdentityDocument.model_validate(raw)

    async def delete_for_user(self, user_id: str) -> None:
        if PydanticObjectId.is_valid(user_id):
            await AppleIdentityDocument.find(
                AppleIdentityDocument.user_id == PydanticObjectId(user_id)
            ).delete()
