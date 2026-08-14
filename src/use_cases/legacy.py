import base64
import binascii

from src.domain.errors import InvalidLinkCode, InvalidPhoto, UserNotFound
from src.repositories.legacy import LegacyRepository
from src.repositories.users import UserRepository
from src.use_cases.profiles import DeleteAccount, UpdateOwnPhoto


class LegacyCompatibility:
    def __init__(
        self,
        legacy: LegacyRepository,
        users: UserRepository,
        photos: UpdateOwnPhoto,
        delete_account: DeleteAccount,
    ) -> None:
        self._legacy = legacy
        self._users = users
        self._photos = photos
        self._delete_account = delete_account

    async def by_code(self, code_hash: str) -> object:
        user = await self._legacy.by_code_hash(code_hash)
        if user is None:
            raise InvalidLinkCode()
        return user

    async def by_telegram_id(self, tg_id: int) -> object:
        user = await self._users.get_by_tg_id(tg_id)
        if user is None:
            raise UserNotFound()
        return user

    async def replace_photo(self, tg_id: int, encoded: str) -> object:
        user = await self.by_telegram_id(tg_id)
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise InvalidPhoto("invalid base64 photo") from error
        return await self._photos.replace(str(getattr(user, "id")), data)

    async def delete_photo(self, tg_id: int) -> object:
        user = await self.by_telegram_id(tg_id)
        return await self._photos.delete(str(getattr(user, "id")))

    async def delete(self, tg_id: int, code_hash: str) -> None:
        user = await self._legacy.validate_user_hash(tg_id, code_hash)
        if user is None:
            raise InvalidLinkCode()
        await self._delete_account.execute(str(user.id))
