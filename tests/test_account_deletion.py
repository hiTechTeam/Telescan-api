from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, status

from src.api.v1.server.routers import routing
from src.core.s3 import S3Client
from src.core.schemas.request_schemas import DeleteUserAccountRequest


VALID_HASH = "a" * 64


@pytest.mark.asyncio
async def test_delete_account_removes_files_and_database_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(
        tg_id=123,
        code=VALID_HASH,
        photo_s3_link="https://storage.example/users/123/current.jpg",
        delete=AsyncMock(),
    )
    monkeypatch.setattr(
        routing,
        "User",
        SimpleNamespace(
            tg_id=0,
            find_one=AsyncMock(return_value=user),
        ),
    )
    monkeypatch.setattr(
        routing,
        "delete_all_user_photos",
        AsyncMock(),
    )

    response = await routing.delete_user_account(
        DeleteUserAccountRequest(
            tgId=123,
            hashedCode=VALID_HASH,
        )
    )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    routing.delete_all_user_photos.assert_awaited_once_with(user)
    user.delete.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_delete_account_rejects_invalid_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(
        tg_id=123,
        code="b" * 64,
        photo_s3_link=None,
        delete=AsyncMock(),
    )
    monkeypatch.setattr(
        routing,
        "User",
        SimpleNamespace(
            tg_id=0,
            find_one=AsyncMock(return_value=user),
        ),
    )
    monkeypatch.setattr(
        routing,
        "delete_all_user_photos",
        AsyncMock(),
    )

    with pytest.raises(HTTPException) as error:
        await routing.delete_user_account(
            DeleteUserAccountRequest(
                tgId=123,
                hashedCode=VALID_HASH,
            )
        )

    assert error.value.status_code == status.HTTP_403_FORBIDDEN
    routing.delete_all_user_photos.assert_not_awaited()
    user.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_account_keeps_database_record_when_storage_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(
        tg_id=123,
        code=VALID_HASH,
        photo_s3_link=None,
        delete=AsyncMock(),
    )
    monkeypatch.setattr(
        routing,
        "User",
        SimpleNamespace(
            tg_id=0,
            find_one=AsyncMock(return_value=user),
        ),
    )
    monkeypatch.setattr(
        routing,
        "delete_all_user_photos",
        AsyncMock(side_effect=RuntimeError("storage unavailable")),
    )

    with pytest.raises(HTTPException) as error:
        await routing.delete_user_account(
            DeleteUserAccountRequest(
                tgId=123,
                hashedCode=VALID_HASH,
            )
        )

    assert error.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    user.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_all_user_photos_covers_legacy_and_current_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s3_client = routing.s.s3_client
    delete_files = AsyncMock()
    delete_prefix = AsyncMock()
    monkeypatch.setattr(s3_client, "delete_files", delete_files)
    monkeypatch.setattr(s3_client, "delete_prefix", delete_prefix)
    monkeypatch.setattr(
        s3_client,
        "object_name_from_public_url",
        Mock(return_value="users/123/current.jpg"),
    )
    user = SimpleNamespace(
        tg_id=123,
        photo_s3_link="https://storage.example/users/123/current.jpg",
    )

    await routing.delete_all_user_photos(user)

    delete_files.assert_awaited_once_with(
        ["123.jpg", "users/123/current.jpg"]
    )
    delete_prefix.assert_awaited_once_with("users/123/")


@pytest.mark.asyncio
async def test_delete_prefix_reads_every_s3_page() -> None:
    client = S3Client(
        access_key="test",
        secret_key="test",
        endpoint_url="https://s3.example",
        public_base_url="https://storage.example",
        bucket_name="test-bucket",
    )
    fake_s3 = SimpleNamespace(
        list_objects_v2=AsyncMock(
            side_effect=[
                {
                    "Contents": [{"Key": "users/123/one.jpg"}],
                    "IsTruncated": True,
                    "NextContinuationToken": "page-2",
                },
                {
                    "Contents": [{"Key": "users/123/two.jpg"}],
                    "IsTruncated": False,
                },
            ]
        )
    )

    @asynccontextmanager
    async def get_client():
        yield fake_s3

    client.get_client = get_client  # type: ignore[method-assign]
    client.delete_files = AsyncMock()  # type: ignore[method-assign]

    await client.delete_prefix("users/123/")

    assert fake_s3.list_objects_v2.await_count == 2
    fake_s3.list_objects_v2.assert_any_await(
        Bucket="test-bucket",
        Prefix="users/123/",
        ContinuationToken="page-2",
    )
    client.delete_files.assert_awaited_once_with(
        ["users/123/one.jpg", "users/123/two.jpg"]
    )
