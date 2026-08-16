from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.api.routers.auth import link_device, refresh_session
from src.api.routers.profiles import get_public_profile
from src.domain.entities import AuthContext
from src.schemas.auth import LinkRequest, RefreshRequest


class RecordingLimiter:
    def __init__(self) -> None:
        self.keys: list[str] = []

    async def check(self, key: str, limit: int, window_seconds: int) -> None:
        self.keys.append(key)


@pytest.mark.asyncio
async def test_link_limit_is_scoped_to_device() -> None:
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
    await link_device(LinkRequest(code="12345678", deviceId=device_id), container)

    assert limiter.keys == [f"auth-link:{device_id}"]


@pytest.mark.asyncio
async def test_refresh_limit_does_not_depend_on_proxy_ip() -> None:
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
    await refresh_session(payload, container)

    assert len(limiter.keys) == 1
    assert limiter.keys[0].startswith("auth-refresh:")
    assert "r" * 48 not in limiter.keys[0]


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
