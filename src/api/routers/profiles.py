# ruff: noqa
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from src.dependencies.auth import get_current_auth
from src.dependencies.container import Container, get_container
from src.domain.entities import AuthContext
from src.schemas.users import ProfileResponse

router = APIRouter(prefix="/api/v1/profiles", tags=["profiles"])


@router.get("/{telescan_id}", response_model=ProfileResponse)
async def get_public_profile(
    telescan_id: UUID,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    container: Annotated[Container, Depends(get_container)],
) -> ProfileResponse:
    await container.rate_limiter.check(
        f"profile:{auth.user_id}", limit=120, window_seconds=60
    )
    user = await container.get_public_profile.execute(auth.user_id, telescan_id)
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
