import hashlib
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from src.api.request_scope import request_client_ip
from src.dependencies.auth import get_current_auth
from src.dependencies.container import Container, get_container
from src.domain.entities import AuthContext
from src.schemas.auth import (
    AppleSignInRequest,
    LinkRequest,
    RefreshRequest,
    TokenResponse,
)
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
        bio=getattr(user, "bio", None),
        photo_url=getattr(user, "photo_s3_link", None),
        telegram_linked=bool(
            getattr(user, "tg_id", None)
            and str(getattr(user, "tg_username", "") or "").strip()
        ),
    )


@router.post("/link", response_model=LinkedAccountResponse)
async def link_device_for_development(
    request: Request,
    payload: LinkRequest,
    container: Annotated[Container, Depends(get_container)],
) -> LinkedAccountResponse:
    if not container.settings.enable_legacy_api:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await container.rate_limiter.check(
        f"auth-link:ip:{request_client_ip(request)}", limit=30, window_seconds=300
    )
    await container.rate_limiter.check(
        f"auth-link:device:{payload.device_id}", limit=10, window_seconds=300
    )
    tokens, user = await container.link_device.execute(payload.code, payload.device_id)
    return LinkedAccountResponse(tokens=_tokens(tokens), profile=_profile(user))


@router.post("/apple", response_model=LinkedAccountResponse)
async def sign_in_with_apple(
    request: Request,
    payload: AppleSignInRequest,
    container: Annotated[Container, Depends(get_container)],
) -> LinkedAccountResponse:
    await container.rate_limiter.check(
        f"auth-apple:ip:{request_client_ip(request)}", limit=30, window_seconds=300
    )
    await container.rate_limiter.check(
        f"auth-apple:device:{payload.device_id}", limit=10, window_seconds=300
    )
    tokens, user = await container.sign_in_with_apple.execute(
        payload.identity_token,
        payload.nonce,
        payload.device_id,
        payload.name,
    )
    return LinkedAccountResponse(tokens=_tokens(tokens), profile=_profile(user))


@router.post("/refresh", response_model=TokenResponse)
async def refresh_session(
    request: Request,
    payload: RefreshRequest,
    container: Annotated[Container, Depends(get_container)],
) -> TokenResponse:
    token_scope = hashlib.sha256(payload.refresh_token.encode("utf-8")).hexdigest()
    await container.rate_limiter.check(
        f"auth-refresh:ip:{request_client_ip(request)}",
        limit=60,
        window_seconds=60,
    )
    await container.rate_limiter.check(
        f"auth-refresh:token:{token_scope}", limit=30, window_seconds=60
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


@router.get(
    "/logout-all/requests/{confirmation_id}",
    response_model=ConfirmationResponse,
)
async def get_logout_all_status(
    confirmation_id: UUID,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    container: Annotated[Container, Depends(get_container)],
) -> ConfirmationResponse:
    result = await container.get_confirmation_status.execute(
        confirmation_id, auth.user_id
    )
    return ConfirmationResponse(
        confirmation_id=result.confirmation_id,
        status=result.status,
    )
