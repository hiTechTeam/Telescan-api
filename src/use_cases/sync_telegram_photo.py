import logging

from src.domain.enums import TelegramPhotoState
from src.domain.errors import InvalidPhoto, UserNotFound
from src.domain.ports import UserRepositoryPort
from src.services.account_operations import AccountOperationGuard
from src.services.photos import PhotoService


logger = logging.getLogger(__name__)


class SyncTelegramPhoto:
    """Synchronize Telegram's current avatar without issuing a new link code."""

    def __init__(
        self,
        users: UserRepositoryPort,
        photos: PhotoService,
        account_operations: AccountOperationGuard | None = None,
    ) -> None:
        self._users = users
        self._photos = photos
        self._account_operations = account_operations

    async def execute(
        self,
        tg_id: int,
        photo: bytes | None,
        photo_state: TelegramPhotoState,
    ) -> None:
        if photo_state == TelegramPhotoState.UNCHANGED:
            return
        if photo_state == TelegramPhotoState.PRESENT and photo is None:
            raise InvalidPhoto("photo is required when photo_state is present")
        if photo_state == TelegramPhotoState.ABSENT and photo is not None:
            raise InvalidPhoto("photo must be omitted when photo_state is absent")

        if self._account_operations is None:
            await self._sync_locked(tg_id, photo, photo_state)
            return

        # Use the same lock order as link-code issuance: Telegram identity first,
        # canonical account second. This prevents a late photo task from racing
        # account linking, merging, or deletion.
        async with self._account_operations.exclusive(f"telegram:{tg_id}"):
            user = await self._users.get_by_tg_id(tg_id)
            if user is None:
                raise UserNotFound()
            async with self._account_operations.admit(str(getattr(user, "id"))):
                await self._sync_user(user, photo, photo_state)

    async def _sync_locked(
        self,
        tg_id: int,
        photo: bytes | None,
        photo_state: TelegramPhotoState,
    ) -> None:
        user = await self._users.get_by_tg_id(tg_id)
        if user is None:
            raise UserNotFound()
        await self._sync_user(user, photo, photo_state)

    async def _sync_user(
        self,
        user: object,
        photo: bytes | None,
        photo_state: TelegramPhotoState,
    ) -> None:
        user_id = str(getattr(user, "id"))
        old_url = getattr(user, "photo_s3_link", None)

        if photo_state == TelegramPhotoState.ABSENT:
            await self._users.update_photo(user_id, None)
            await self._photos.delete_all(getattr(user, "telescan_id"), old_url)
            return

        assert photo is not None
        new_url = await self._photos.upload(getattr(user, "telescan_id"), photo)
        try:
            await self._users.update_photo(user_id, new_url)
        except Exception:
            try:
                await self._photos.delete_by_url(new_url)
            except Exception:
                logger.exception(
                    "Could not remove unreferenced Telegram photo for user %s",
                    user_id,
                )
            raise

        if old_url and old_url != new_url:
            try:
                await self._photos.delete_by_url(old_url)
            except Exception:
                # The new database value is already authoritative. A cleanup
                # failure must not make the bot upload duplicate replacements.
                logger.exception(
                    "Could not remove obsolete Telegram photo for user %s",
                    user_id,
                )
