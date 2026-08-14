from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from src.dependencies.auth import get_current_auth
from src.dependencies.container import Container, get_container
from src.domain.entities import AuthContext
from src.schemas.auth import LinkRequest, RefreshRequest, TokenResponse
from src.schemas.internal import ConfirmationResponse
from src.schemas.users import LinkedAccountResponse, ProfileResponse

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _tokens(value: object) -> TokenResponse:
    return TokenResponse(
        access_token=getattr(value, "access_token"),
        refresh_token=getattr(value, "refresh_token"),
        expires_in=getattr(value, "expires_in"),
    )


def _profile(user: object) -> ProfileResponse:
    return ProfileResponse(
        telescan_id=getattr(user, "telescan_id"),
        name=getattr(user, "tg_name", None),
        username=getattr(user, "tg_username", None),
        photo_url=getattr(user, "photo_s3_link", None),
    )


@router.post("/link", response_model=LinkedAccountResponse)
async def link_device(
    payload: LinkRequest,
    request: Request,
    container: Annotated[Container, Depends(get_container)],
) -> LinkedAccountResponse:
    client = request.client.host if request.client else "unknown"
    await container.rate_limiter.check(
        f"auth-link:{client}:{payload.device_id}", limit=10, window_seconds=300
    )
    tokens, user = await container.link_device.execute(payload.code, payload.device_id)
    return LinkedAccountResponse(tokens=_tokens(tokens), profile=_profile(user))


@router.post("/refresh", response_model=TokenResponse)
async def refresh_session(
    payload: RefreshRequest,
    request: Request,
    container: Annotated[Container, Depends(get_container)],
) -> TokenResponse:
    client = request.client.host if request.client else "unknown"
    await container.rate_limiter.check(
        f"auth-refresh:{client}", limit=30, window_seconds=60
    )
    return _tokens(await container.refresh_session.execute(payload.refresh_token))


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def logout_current_session(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    await container.sessions.revoke(auth.session_id, datetime.now(UTC))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout-all/request", response_model=ConfirmationResponse)
async def request_logout_all(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    container: Annotated[Container, Depends(get_container)],
) -> ConfirmationResponse:
    result = await container.request_logout_all.execute(auth.user_id)
    return ConfirmationResponse(
        confirmation_id=result.confirmation_id,
        status=result.status,
    )
