from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Request, UploadFile

from src.api.routers.auth import link_device, refresh_session
from src.api.routers.profiles import get_public_profile
from src.api.routers.users import replace_my_photo, update_my_profile
from src.api.request_scope import request_client_ip
from src.domain.entities import AuthContext
from src.schemas.auth import LinkRequest, RefreshRequest
from src.schemas.users import ProfileUpdateRequest


class RecordingLimiter:
    def __init__(self) -> None:
        self.keys: list[str] = []

    async def check(self, key: str, limit: int, window_seconds: int) -> None:
        self.keys.append(key)


def make_request(
    client_ip: str = "198.51.100.10",
    real_ip: str | None = None,
) -> Request:
    headers = [] if real_ip is None else [(b"x-real-ip", real_ip.encode("ascii"))]
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": headers,
            "client": (client_ip, 12345),
        }
    )


@pytest.mark.asyncio
async def test_link_limit_is_scoped_to_client_and_device() -> None:
    device_id = uuid4()
    limiter = RecordingLimiter()
    tokens = SimpleNamespace(
        access_token="access",
        refresh_token="refresh",
        expires_in=900,
    )
    user = SimpleNamespace(
        telescan_id=uuid4(),
        tg_name="Ada",
        tg_username="ada",
        photo_s3_link=None,
    )

    async def execute(*_):
        return tokens, user

    container = SimpleNamespace(
        rate_limiter=limiter,
        link_device=SimpleNamespace(execute=execute),
    )
    await link_device(
        make_request(real_ip="203.0.113.20"),
        LinkRequest(code="12345678", deviceId=device_id),
        container,
    )

    assert limiter.keys == [
        "auth-link:ip:203.0.113.20",
        f"auth-link:device:{device_id}",
    ]


@pytest.mark.asyncio
async def test_refresh_limit_covers_client_and_hides_token() -> None:
    limiter = RecordingLimiter()
    tokens = SimpleNamespace(
        access_token="access",
        refresh_token="new-refresh",
        expires_in=900,
    )

    async def execute(*_):
        return tokens

    container = SimpleNamespace(
        rate_limiter=limiter,
        refresh_session=SimpleNamespace(execute=execute),
    )
    payload = RefreshRequest(refreshToken="r" * 48)
    await refresh_session(make_request(), payload, container)

    assert len(limiter.keys) == 2
    assert limiter.keys[0] == "auth-refresh:ip:198.51.100.10"
    assert limiter.keys[1].startswith("auth-refresh:token:")
    assert all("r" * 48 not in key for key in limiter.keys)


def test_client_address_uses_valid_edge_header_and_rejects_invalid_value() -> None:
    assert request_client_ip(make_request(real_ip="2001:db8::1")) == "2001:db8::1"
    assert request_client_ip(make_request(real_ip="not-an-address")) == "198.51.100.10"


@pytest.mark.asyncio
async def test_profile_limit_is_scoped_to_authenticated_user() -> None:
    limiter = RecordingLimiter()
    target_id = uuid4()
    user = SimpleNamespace(
        telescan_id=target_id,
        tg_name="Ada",
        tg_username="ada",
        photo_s3_link=None,
    )

    async def execute(*_):
        return user

    container = SimpleNamespace(
        rate_limiter=limiter,
        get_public_profile=SimpleNamespace(execute=execute),
    )
    auth = AuthContext(user_id="requester", session_id="session")
    await get_public_profile(target_id, auth, container)

    assert limiter.keys == ["profile:requester"]


@pytest.mark.asyncio
async def test_photo_upload_is_rate_limited_per_authenticated_user() -> None:
    limiter = RecordingLimiter()
    user = SimpleNamespace(
        telescan_id=uuid4(),
        tg_name="Ada",
        tg_username="ada",
        photo_s3_link="https://storage.example/photo.jpg",
    )

    async def replace(*_):
        return user

    container = SimpleNamespace(
        rate_limiter=limiter,
        settings=SimpleNamespace(max_photo_bytes=1024),
        update_own_photo=SimpleNamespace(replace=replace),
    )
    auth = AuthContext(user_id="requester", session_id="session")
    upload = UploadFile(filename="profile.jpg", file=BytesIO(b"photo"))

    await replace_my_photo(upload, auth, container)

    assert limiter.keys == ["photo:requester"]


@pytest.mark.asyncio
async def test_bio_update_is_rate_limited_per_authenticated_user() -> None:
    limiter = RecordingLimiter()
    user = SimpleNamespace(
        telescan_id=uuid4(),
        tg_name="Ada",
        tg_username="ada",
        bio="Open to meetups",
        photo_s3_link=None,
    )

    async def execute(*_):
        return user

    container = SimpleNamespace(
        rate_limiter=limiter,
        update_own_bio=SimpleNamespace(execute=execute),
    )
    auth = AuthContext(user_id="requester", session_id="session")

    response = await update_my_profile(
        ProfileUpdateRequest(bio="Open to meetups"), auth, container
    )

    assert response.bio == "Open to meetups"
    assert limiter.keys == ["profile-update:requester"]
