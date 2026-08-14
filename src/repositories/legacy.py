"""Short-lived adapter for the pre-token iOS release.

It deliberately reads the old `users.code` field without adding it back to the
new User model.  The router is disabled by default and can be removed after the
new iOS release is broadly adopted.
"""

from beanie import PydanticObjectId

from src.infrastructure.mongodb.documents import UserDocument


class LegacyRepository:
    async def set_code_hash(self, user_id: str, code_hash: str) -> None:
        if not PydanticObjectId.is_valid(user_id):
            raise LookupError(user_id)
        await UserDocument.get_pymongo_collection().update_one(
            {"_id": PydanticObjectId(user_id)},
            {"$set": {"code": code_hash}},
        )

    async def by_code_hash(self, code_hash: str) -> UserDocument | None:
        raw = await UserDocument.get_pymongo_collection().find_one({"code": code_hash})
        return UserDocument.model_validate(raw) if raw else None

    async def validate_user_hash(
        self, tg_id: int, code_hash: str
    ) -> UserDocument | None:
        raw = await UserDocument.get_pymongo_collection().find_one(
            {"tg_id": tg_id, "code": code_hash}
        )
        return UserDocument.model_validate(raw) if raw else None
