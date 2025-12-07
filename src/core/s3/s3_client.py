import mimetypes
from aiobotocore.session import get_session, AioBaseClient
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

__all__ = ["S3Client"]


class S3Client:
    def __init__(
        self,
        access_key: str,
        secret_key: str,
        endpoint_url: str,
        bucket_name: str,
    ) -> None:
        self.config = {
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "endpoint_url": endpoint_url,
        }
        self.bucket_name = bucket_name
        self.session = get_session()

    @asynccontextmanager
    async def get_client(self) -> AsyncGenerator[AioBaseClient, None]:
        async with self.session.create_client("s3", **self.config) as client:
            yield client

    async def upload_file(
        self, file_bytes: bytes, object_name: str, content_type: Optional[str] = None
    ) -> str:
        if content_type is None:
            content_type_guess, _ = mimetypes.guess_type(object_name)
            content_type = content_type_guess or "application/octet-stream"

        async with self.get_client() as client:
            await client.put_object(
                Bucket=self.bucket_name,
                Key=object_name,
                Body=file_bytes,
                ContentType=content_type,
            )  # type: ignore

        return f"{self.config['endpoint_url'].rstrip('/')}/{self.bucket_name}/{object_name}"

    async def upload_photo(self, img: bytes, object_name: str) -> Optional[str]:

        return await self.upload_file(
            file_bytes=img,
            object_name=object_name,
            content_type="image/jpeg",
        )

    async def delete_photo(self, object_name: str) -> None:
        async with self.get_client() as client:
            await client.delete_object(Bucket=self.bucket_name, Key=object_name)  # type: ignore
