from contextlib import asynccontextmanager
import os
import ssl
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
        ca_bundle = os.environ.get("AWS_CA_BUNDLE")
        if ca_bundle is None:
            ca_bundle = ssl.get_default_verify_paths().cafile
        if ca_bundle:
            self._client_config["verify"] = ca_bundle
        self._session = get_session()
        self._public_base_url = public_base_url.rstrip("/")
        self._bucket_name = bucket_name

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[Any]:
        async with self._session.create_client("s3", **self._client_config) as client:
            yield client

    async def upload(self, data: bytes, object_name: str, content_type: str) -> str:
        async with self._client() as client:
            await client.put_object(
                Bucket=self._bucket_name,
                Key=object_name,
                Body=data,
                ContentType=content_type,
            )
        return f"{self._public_base_url}/{object_name}"

    async def copy_by_url(self, source_url: str, object_name: str) -> str:
        source_name = self._object_name(source_url)
        if not source_name:
            raise ValueError("photo URL does not belong to configured storage")
        async with self._client() as client:
            await client.copy_object(
                Bucket=self._bucket_name,
                Key=object_name,
                CopySource={"Bucket": self._bucket_name, "Key": source_name},
                MetadataDirective="COPY",
            )
        return f"{self._public_base_url}/{object_name}"

    async def delete_by_url(self, public_url: str) -> None:
        object_name = self._object_name(public_url)
        if object_name:
            async with self._client() as client:
                await client.delete_object(Bucket=self._bucket_name, Key=object_name)

    def _object_name(self, public_url: str) -> str | None:
        prefix = f"{self._public_base_url}/"
        if not public_url.startswith(prefix):
            return None
        object_name = unquote(urlparse(public_url).path.lstrip("/"))
        base_path = urlparse(self._public_base_url).path.lstrip("/")
        if base_path and object_name.startswith(f"{base_path}/"):
            object_name = object_name[len(base_path) + 1 :]
        return object_name or None

    async def delete_user_prefix(self, telescan_id: UUID) -> None:
        prefix = f"users/{telescan_id}/"
        await self._delete_prefix(prefix)

    async def delete_report_prefix(self, report_id: UUID) -> None:
        prefix = f"moderation/reports/{report_id}/"
        await self._delete_prefix(prefix)

    async def _delete_prefix(self, prefix: str) -> None:
        continuation_token: str | None = None
        async with self._client() as client:
            while True:
                request: dict[str, Any] = {
                    "Bucket": self._bucket_name,
                    "Prefix": prefix,
                }
                if continuation_token:
                    request["ContinuationToken"] = continuation_token
                page = await client.list_objects_v2(**request)
                objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
                if objects:
                    result = await client.delete_objects(
                        Bucket=self._bucket_name,
                        Delete={"Objects": objects, "Quiet": True},
                    )
                    errors = result.get("Errors", [])
                    if errors:
                        raise RuntimeError(
                            "S3 prefix deletion returned per-object failures"
                        )
                if not page.get("IsTruncated"):
                    break
                continuation_token = page.get("NextContinuationToken")
                if not continuation_token:
                    break
            verification = await client.list_objects_v2(
                Bucket=self._bucket_name,
                Prefix=prefix,
                MaxKeys=1,
            )
            if verification.get("Contents") or verification.get("IsTruncated"):
                raise RuntimeError("S3 prefix is not empty after deletion")
