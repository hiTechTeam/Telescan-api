from datetime import UTC, datetime
from uuid import UUID

from src.domain.errors import UserNotFound
from src.domain.ports import (
    ConfirmationRepositoryPort,
    LinkCodeRepositoryPort,
    SessionRepositoryPort,
    UserRepositoryPort,
)
from src.services.photos import PhotoService


class GetOwnProfile:
    def __init__(self, users: UserRepositoryPort) -> None:
        self._users = users

    async def execute(self, user_id: str) -> object:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFound()
        return user


class GetPublicProfile:
    def __init__(self, users: UserRepositoryPort) -> None:
        self._users = users

    async def execute(self, telescan_id: UUID) -> object:
        user = await self._users.get_by_telescan_id(telescan_id)
        if user is None:
            raise UserNotFound()
        return user


class UpdateOwnPhoto:
    def __init__(self, users: UserRepositoryPort, photos: PhotoService) -> None:
        self._users = users
        self._photos = photos

    async def replace(self, user_id: str, photo: bytes) -> object:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFound()
        url = await self._photos.replace(
            getattr(user, "telescan_id"), photo, getattr(user, "photo_s3_link", None)
        )
        return await self._users.update_photo(user_id, url)

    async def delete(self, user_id: str) -> object:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFound()
        await self._photos.delete_all(
            getattr(user, "telescan_id"), getattr(user, "photo_s3_link", None)
        )
        return await self._users.update_photo(user_id, None)


class DeleteAccount:
    def __init__(
        self,
        users: UserRepositoryPort,
        link_codes: LinkCodeRepositoryPort,
        sessions: SessionRepositoryPort,
        confirmations: ConfirmationRepositoryPort,
        photos: PhotoService,
    ) -> None:
        self._users = users
        self._link_codes = link_codes
        self._sessions = sessions
        self._confirmations = confirmations
        self._photos = photos

    async def execute(self, user_id: str) -> None:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFound()
        now = datetime.now(UTC)
        # Revocation is first so a partial storage failure never leaves a usable session.
        await self._sessions.revoke_all(user_id, now)
        await self._photos.delete_all(
            getattr(user, "telescan_id"), getattr(user, "photo_s3_link", None)
        )
        await self._link_codes.delete_for_user(user_id)
        await self._confirmations.delete_for_user(user_id)
        await self._sessions.delete_for_user(user_id)
        await self._users.delete(user_id)
