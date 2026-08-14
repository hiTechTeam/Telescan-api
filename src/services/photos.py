from uuid import UUID, uuid4

from src.domain.errors import InvalidPhoto
from src.domain.ports import PhotoStoragePort


class PhotoService:
    _FORMATS = (
        (b"\xff\xd8\xff", "image/jpeg", "jpg"),
        (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
        (b"RIFF", "image/webp", "webp"),
    )

    def __init__(self, storage: PhotoStoragePort, max_bytes: int) -> None:
        self._storage = storage
        self._max_bytes = max_bytes

    def validate(self, data: bytes) -> tuple[str, str]:
        if not data or len(data) > self._max_bytes:
            raise InvalidPhoto("photo is empty or too large")
        for signature, content_type, extension in self._FORMATS:
            if data.startswith(signature):
                if content_type == "image/webp" and data[8:12] != b"WEBP":
                    break
                return content_type, extension
        raise InvalidPhoto("unsupported photo format")

    async def replace(
        self,
        telescan_id: UUID,
        data: bytes,
        old_url: str | None,
    ) -> str:
        content_type, extension = self.validate(data)
        name = f"users/{telescan_id}/{uuid4().hex}.{extension}"
        new_url = await self._storage.upload(data, name, content_type)
        if old_url and old_url != new_url:
            await self._storage.delete_by_url(old_url)
        return new_url

    async def delete_all(self, telescan_id: UUID, current_url: str | None) -> None:
        if current_url:
            await self._storage.delete_by_url(current_url)
        await self._storage.delete_user_prefix(telescan_id)
