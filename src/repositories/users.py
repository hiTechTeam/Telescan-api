from datetime import UTC, datetime
from uuid import UUID, uuid4

from beanie import PydanticObjectId
from pymongo import ReturnDocument

from src.infrastructure.mongodb.documents import UserDocument


class UserRepository:
    async def create_unlinked(self) -> UserDocument:
        now = datetime.now(UTC)
        user = UserDocument(
            telescan_id=uuid4(),
            tg_id=None,
            created_at=now,
            updated_at=now,
        )
        await user.insert()
        return user

    async def upsert_telegram_profile(
        self,
        tg_id: int,
        tg_name: str | None,
        tg_username: str | None,
    ) -> UserDocument:
        now = datetime.now(UTC)
        collection = UserDocument.get_pymongo_collection()
        raw = await collection.find_one_and_update(
            {"tg_id": tg_id},
            {
                "$set": {
                    "tg_name": tg_name,
                    "tg_username": tg_username,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "telescan_id": uuid4(),
                    "created_at": now,
                    "bio": None,
                    "photo_s3_link": None,
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return UserDocument.model_validate(raw)

    async def get_by_id(self, user_id: str) -> UserDocument | None:
        if not PydanticObjectId.is_valid(user_id):
            return None
        return await UserDocument.get(PydanticObjectId(user_id))

    async def get_by_telescan_id(self, telescan_id: UUID) -> UserDocument | None:
        return await UserDocument.find_one(UserDocument.telescan_id == telescan_id)

    async def get_by_tg_id(self, tg_id: int) -> UserDocument | None:
        return await UserDocument.find_one(UserDocument.tg_id == tg_id)

    async def update_bio(self, user_id: str, bio: str | None) -> UserDocument:
        user = await self.get_by_id(user_id)
        if user is None:
            raise LookupError(user_id)
        user.bio = bio
        user.updated_at = datetime.now(UTC)
        await user.save()
        return user

    async def update_photo(self, user_id: str, photo_url: str | None) -> UserDocument:
        user = await self.get_by_id(user_id)
        if user is None:
            raise LookupError(user_id)
        user.photo_s3_link = photo_url
        user.updated_at = datetime.now(UTC)
        await user.save()
        return user

    async def delete(self, user_id: str) -> None:
        user = await self.get_by_id(user_id)
        if user is not None:
            await user.delete()
