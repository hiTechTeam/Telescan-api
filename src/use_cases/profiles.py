from datetime import UTC, datetime
from uuid import UUID

from src.domain.errors import UserNotFound
from src.domain.ports import (
    BlockRepositoryPort,
    ConfirmationRepositoryPort,
    LinkCodeRepositoryPort,
    ReviewCodeRepositoryPort,
    ReportRepositoryPort,
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
    def __init__(
        self,
        users: UserRepositoryPort,
        blocks: BlockRepositoryPort,
    ) -> None:
        self._users = users
        self._blocks = blocks

    async def execute(self, requester_id: str, telescan_id: UUID) -> object:
        user = await self._users.get_by_telescan_id(telescan_id)
        if user is None:
            raise UserNotFound()
        if await self._blocks.exists_between(requester_id, str(getattr(user, "id"))):
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
        reports: ReportRepositoryPort,
        blocks: BlockRepositoryPort,
        photos: PhotoService,
        review_codes: ReviewCodeRepositoryPort | None = None,
    ) -> None:
        self._users = users
        self._link_codes = link_codes
        self._sessions = sessions
        self._confirmations = confirmations
        self._reports = reports
        self._blocks = blocks
        self._photos = photos
        self._review_codes = review_codes

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
        if self._review_codes is not None:
            await self._review_codes.delete_for_user(user_id)
        await self._confirmations.delete_for_user(user_id)
        await self._blocks.delete_for_user(user_id)
        await self._reports.anonymize_user(user_id)
        await self._sessions.delete_for_user(user_id)
        await self._users.delete(user_id)
