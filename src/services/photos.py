from pathlib import PurePosixPath
from urllib.parse import urlparse
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

    async def upload(
        self,
        telescan_id: UUID,
        data: bytes,
    ) -> str:
        content_type, extension = self.validate(data)
        name = f"users/{telescan_id}/{uuid4().hex}.{extension}"
        return await self._storage.upload(data, name, content_type)

    async def delete_by_url(self, url: str) -> None:
        await self._storage.delete_by_url(url)

    async def delete_report_prefix(self, report_id: UUID) -> None:
        await self._storage.delete_report_prefix(report_id)

    async def copy_for_report(self, report_id: UUID, source_url: str) -> str:
        suffix = PurePosixPath(urlparse(source_url).path).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            suffix = ".img"
        object_name = f"moderation/reports/{report_id}/evidence{suffix}"
        return await self._storage.copy_by_url(source_url, object_name)

    async def delete_all(self, telescan_id: UUID, current_url: str | None) -> None:
        if current_url:
            await self._storage.delete_by_url(current_url)
        await self._storage.delete_user_prefix(telescan_id)
