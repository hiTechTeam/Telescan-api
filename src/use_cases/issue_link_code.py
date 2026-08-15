import logging
from datetime import UTC, datetime, timedelta

from src.domain.entities import IssuedLinkCode
from src.domain.enums import TelegramPhotoState
from src.domain.errors import LinkCodeCollision
from src.domain.ports import (
    LegacyCodePublisherPort,
    LinkCodeRepositoryPort,
    UserRepositoryPort,
)
from src.services.codes import LinkCodeService
from src.services.photos import PhotoService


logger = logging.getLogger(__name__)


class IssueLinkCode:
    def __init__(
        self,
        users: UserRepositoryPort,
        link_codes: LinkCodeRepositoryPort,
        codes: LinkCodeService,
        photos: PhotoService,
        ttl_seconds: int,
        legacy_codes: LegacyCodePublisherPort | None = None,
    ) -> None:
        self._users = users
        self._link_codes = link_codes
        self._codes = codes
        self._photos = photos
        self._ttl_seconds = ttl_seconds
        self._legacy_codes = legacy_codes

    async def execute(
        self,
        tg_id: int,
        tg_name: str | None,
        tg_username: str | None,
        photo: bytes | None,
        now: datetime | None = None,
        photo_state: TelegramPhotoState = TelegramPhotoState.UNCHANGED,
    ) -> IssuedLinkCode:
        current_time = now or datetime.now(UTC)
        user = await self._users.upsert_telegram_profile(tg_id, tg_name, tg_username)

        if photo is not None:
            try:
                photo_url = await self._photos.replace(
                    getattr(user, "telescan_id"),
                    photo,
                    getattr(user, "photo_s3_link", None),
                )
                user = await self._users.update_photo(
                    str(getattr(user, "id")), photo_url
                )
            except Exception:
                logger.exception(
                    "Could not synchronize Telegram photo for user %s; "
                    "continuing link-code issuance",
                    getattr(user, "id", "unknown"),
                )
        elif photo_state == TelegramPhotoState.ABSENT and getattr(
            user, "photo_s3_link", None
        ):
            old_photo_url = getattr(user, "photo_s3_link")
            try:
                user = await self._users.update_photo(str(getattr(user, "id")), None)
            except Exception:
                logger.exception(
                    "Could not clear obsolete Telegram photo for user %s; "
                    "continuing link-code issuance",
                    getattr(user, "id", "unknown"),
                )
            else:
                try:
                    await self._photos.delete_all(
                        getattr(user, "telescan_id"),
                        old_photo_url,
                    )
                except Exception:
                    logger.exception(
                        "Could not delete obsolete Telegram photo objects for user "
                        "%s; continuing link-code issuance",
                        getattr(user, "id", "unknown"),
                    )

        user_id = str(getattr(user, "id"))
        await self._link_codes.revoke_issued(user_id, current_time)
        expires_at = current_time + timedelta(seconds=self._ttl_seconds)

        # A unique index is the final collision guard. Five attempts make an
        # already astronomically unlikely random collision harmless.
        last_error: Exception | None = None
        for _ in range(5):
            code = self._codes.generate()
            try:
                await self._link_codes.create(
                    self._codes.hash(code), user_id, current_time, expires_at
                )
                if self._legacy_codes is not None:
                    await self._legacy_codes.publish(user_id, code)
                return IssuedLinkCode(
                    code=code,
                    expires_at=expires_at,
                    telescan_id=getattr(user, "telescan_id"),
                )
            except LinkCodeCollision as error:
                last_error = error
        raise RuntimeError("could not allocate a unique link code") from last_error
