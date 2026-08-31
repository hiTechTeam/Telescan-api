from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from src.dependencies.auth import get_current_auth
from src.dependencies.container import Container, get_container
from src.domain.entities import AuthContext
from src.schemas.moderation import (
    BlockedProfileResponse,
    ReportCreateRequest,
    ReportResponse,
)

router = APIRouter(prefix="/api/v1", tags=["moderation"])


def _blocked_profile(block: object) -> BlockedProfileResponse:
    return BlockedProfileResponse(
        telescan_id=getattr(block, "blocked_telescan_id"),
        name=getattr(block, "blocked_name", None),
        username=getattr(block, "blocked_username", None),
        photo_url=getattr(block, "blocked_photo_url", None),
        blocked_at=getattr(block, "created_at"),
    )


@router.post(
    "/reports",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_report(
    payload: ReportCreateRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    container: Annotated[Container, Depends(get_container)],
) -> ReportResponse:
    await container.rate_limiter.check(
        f"report:{auth.user_id}", limit=10, window_seconds=3600
    )
    report = await container.submit_report.execute(
        auth.user_id,
        payload.target_telescan_id,
        payload.client_request_id,
        payload.details,
    )
    return ReportResponse(
        report_id=getattr(report, "public_id"),
        status=getattr(report, "status"),
        created_at=getattr(report, "created_at"),
    )


@router.get(
    "/users/me/blocks",
    response_model=list[BlockedProfileResponse],
)
async def list_blocked_users(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    container: Annotated[Container, Depends(get_container)],
) -> list[BlockedProfileResponse]:
    blocks = await container.list_blocked_users.execute(auth.user_id)
    return [_blocked_profile(block) for block in blocks]


@router.put(
    "/users/me/blocks/{target_telescan_id}",
    response_model=BlockedProfileResponse,
)
async def block_user(
    target_telescan_id: UUID,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    container: Annotated[Container, Depends(get_container)],
) -> BlockedProfileResponse:
    await container.rate_limiter.check(
        f"block:{auth.user_id}", limit=60, window_seconds=3600
    )
    block = await container.block_user.execute(auth.user_id, target_telescan_id)
    return _blocked_profile(block)


@router.delete(
    "/users/me/blocks/{target_telescan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unblock_user(
    target_telescan_id: UUID,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    await container.unblock_user.execute(auth.user_id, target_telescan_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
