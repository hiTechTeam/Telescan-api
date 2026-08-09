import mimetypes
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from aiobotocore.session import get_session


class S3Client:
    def __init__(
        self,
        access_key: str,
        secret_key: str,
        endpoint_url: str,
        public_base_url: str,
        bucket_name: str,
    ) -> None:
        self.config = {
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "endpoint_url": endpoint_url,
            "verify": False,
        }
        self.public_base_url = public_base_url.rstrip("/")
        self.bucket_name = bucket_name
        self.session = get_session()

    @asynccontextmanager
    async def get_client(self) -> AsyncGenerator[Any, None]:
        async with self.session.create_client(
            "s3",
            **self.config,
        ) as client:
            yield client

    async def upload_file(
        self,
        file_bytes: bytes,
        object_name: str,
        content_type: str | None = None,
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
                ACL="public-read",
            )

        return f"{self.public_base_url}/{object_name}"

    async def upload_photo(
        self,
        img: bytes,
        object_name: str,
    ) -> str:
        return await self.upload_file(
            file_bytes=img,
            object_name=object_name,
            content_type="image/jpeg",
        )

    async def delete_file(
        self,
        object_name: str,
    ) -> None:
        async with self.get_client() as client:
            await client.delete_object(
                Bucket=self.bucket_name,
                Key=object_name,
            )

    async def delete_by_public_url(
        self,
        public_url: str,
    ) -> None:
        prefix = f"{self.public_base_url}/"

        if not public_url.startswith(prefix):
            raise ValueError("Invalid S3 public URL")

        object_name = public_url[len(prefix) :]

        if not object_name:
            raise ValueError("S3 object name is empty")

        await self.delete_file(object_name)
