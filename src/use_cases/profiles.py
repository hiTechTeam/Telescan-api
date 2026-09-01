import logging
from uuid import UUID

from src.domain.errors import UserNotFound
from src.domain.ports import (
    AppleIdentityRepositoryPort,
    BlockRepositoryPort,
    UserRepositoryPort,
)
from src.services.account_deletions import AccountDeletionService
from src.services.account_operations import AccountOperationGuard
from src.services.photos import PhotoService


logger = logging.getLogger(__name__)


class GetOwnProfile:
    def __init__(self, users: UserRepositoryPort) -> None:
        self._users = users

    async def execute(self, user_id: str) -> object:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFound()
        return user


class GetPublicProfile:
    def __init__(
        self,
        users: UserRepositoryPort,
        blocks: BlockRepositoryPort,
        apple_identities: AppleIdentityRepositoryPort | None = None,
    ) -> None:
        self._users = users
        self._blocks = blocks
        self._apple_identities = apple_identities

    async def execute(self, requester_id: str, telescan_id: UUID) -> object:
        user = await self._users.get_by_telescan_id(telescan_id)
        if user is None:
            raise UserNotFound()
        if self._apple_identities is not None:
            requester_identity = await self._apple_identities.get_by_user_id(
                requester_id
            )
            target_identity = await self._apple_identities.get_by_user_id(
                str(getattr(user, "id"))
            )
            if requester_identity is None or target_identity is None:
                raise UserNotFound()
        if await self._blocks.exists_between(requester_id, str(getattr(user, "id"))):
            raise UserNotFound()
        return user


class UpdateOwnBio:
    def __init__(
        self,
        users: UserRepositoryPort,
        account_operations: AccountOperationGuard | None = None,
    ) -> None:
        self._users = users
        self._account_operations = account_operations

    async def execute(self, user_id: str, bio: str | None) -> object:
        normalized = " ".join(bio.split()) if bio is not None else None
        if self._account_operations is None:
            user = await self._users.get_by_id(user_id)
            if user is None:
                raise UserNotFound()
            return await self._users.update_bio(user_id, normalized or None)
        async with self._account_operations.admit(user_id):
            user = await self._users.get_by_id(user_id)
            if user is None:
                raise UserNotFound()
            return await self._users.update_bio(user_id, normalized or None)


class UpdateOwnPhoto:
    def __init__(
        self,
        users: UserRepositoryPort,
        photos: PhotoService,
        account_operations: AccountOperationGuard | None = None,
    ) -> None:
        self._users = users
        self._photos = photos
        self._account_operations = account_operations

    async def replace(self, user_id: str, photo: bytes) -> object:
        if self._account_operations is None:
            return await self._replace_locked(user_id, photo)
        async with self._account_operations.admit(user_id):
            return await self._replace_locked(user_id, photo)

    async def _replace_locked(self, user_id: str, photo: bytes) -> object:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFound()
        old_url = getattr(user, "photo_s3_link", None)
        url = await self._photos.upload(getattr(user, "telescan_id"), photo)
        try:
            updated = await self._users.update_photo(user_id, url)
        except Exception:
            try:
                await self._photos.delete_by_url(url)
            except Exception:
                logger.exception(
                    "Could not remove unreferenced replacement photo for user %s",
                    user_id,
                )
            raise

        if old_url and old_url != url:
            try:
                await self._photos.delete_by_url(old_url)
            except Exception:
                logger.exception(
                    "Could not remove obsolete profile photo for user %s",
                    user_id,
                )
        return updated

    async def delete(self, user_id: str) -> object:
        if self._account_operations is None:
            return await self._delete_locked(user_id)
        async with self._account_operations.admit(user_id):
            return await self._delete_locked(user_id)

    async def _delete_locked(self, user_id: str) -> object:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFound()
        current_url = getattr(user, "photo_s3_link", None)
        updated = await self._users.update_photo(user_id, None)
        await self._photos.delete_all(getattr(user, "telescan_id"), current_url)
        return updated


class DeleteAccount:
    def __init__(self, deletions: AccountDeletionService) -> None:
        self._deletions = deletions

    async def execute(self, user_id: str) -> None:
        await self._deletions.delete(user_id)
