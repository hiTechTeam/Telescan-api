from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from urllib.parse import unquote, urlparse
from uuid import UUID

from aiobotocore.session import get_session


class S3PhotoStorage:
    def __init__(
        self,
        access_key: str,
        secret_key: str,
        endpoint_url: str,
        public_base_url: str,
        bucket_name: str,
    ) -> None:
        self._client_config = {
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "endpoint_url": endpoint_url,
        }
        self._session = get_session()
        self._public_base_url = public_base_url.rstrip("/")
        self._bucket_name = bucket_name

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[Any]:
        async with self._session.create_client("s3", **self._client_config) as client:
            yield client

    async def upload(
        self, data: bytes, object_name: str, content_type: str
    ) -> str:
        async with self._client() as client:
            await client.put_object(
                Bucket=self._bucket_name,
                Key=object_name,
                Body=data,
                ContentType=content_type,
                ACL="public-read",
            )
        return f"{self._public_base_url}/{object_name}"

    async def delete_by_url(self, public_url: str) -> None:
        prefix = f"{self._public_base_url}/"
        if not public_url.startswith(prefix):
            return
        object_name = unquote(urlparse(public_url).path.lstrip("/"))
        base_path = urlparse(self._public_base_url).path.lstrip("/")
        if base_path and object_name.startswith(f"{base_path}/"):
            object_name = object_name[len(base_path) + 1 :]
        if object_name:
            async with self._client() as client:
                await client.delete_object(Bucket=self._bucket_name, Key=object_name)

    async def delete_user_prefix(self, telescan_id: UUID) -> None:
        prefix = f"users/{telescan_id}/"
        continuation_token: str | None = None
        async with self._client() as client:
            while True:
                request: dict[str, Any] = {"Bucket": self._bucket_name, "Prefix": prefix}
                if continuation_token:
                    request["ContinuationToken"] = continuation_token
                page = await client.list_objects_v2(**request)
                objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
                if objects:
                    await client.delete_objects(
                        Bucket=self._bucket_name,
                        Delete={"Objects": objects, "Quiet": True},
                    )
                if not page.get("IsTruncated"):
                    break
                continuation_token = page.get("NextContinuationToken")
                if not continuation_token:
                    break
