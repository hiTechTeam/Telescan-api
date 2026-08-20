from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile, status

from src.dependencies.auth import get_current_auth
from src.dependencies.container import Container, get_container
from src.domain.entities import AuthContext
from src.schemas.users import ProfileResponse, ProfileUpdateRequest

router = APIRouter(prefix="/api/v1/users/me", tags=["users"])


def _profile(user: object) -> ProfileResponse:
    return ProfileResponse(
        telescan_id=getattr(user, "telescan_id"),
        name=getattr(user, "tg_name", None),
        username=getattr(user, "tg_username", None),
        bio=getattr(user, "bio", None),
        photo_url=getattr(user, "photo_s3_link", None),
    )


@router.get("", response_model=ProfileResponse)
async def get_me(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    container: Annotated[Container, Depends(get_container)],
) -> ProfileResponse:
    return _profile(await container.get_own_profile.execute(auth.user_id))


@router.patch("", response_model=ProfileResponse)
async def update_my_profile(
    payload: ProfileUpdateRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    container: Annotated[Container, Depends(get_container)],
) -> ProfileResponse:
    await container.rate_limiter.check(
        f"profile-update:{auth.user_id}", limit=20, window_seconds=3600
    )
    return _profile(await container.update_own_bio.execute(auth.user_id, payload.bio))


@router.put("/photo", response_model=ProfileResponse)
async def replace_my_photo(
    photo: Annotated[UploadFile, File()],
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    container: Annotated[Container, Depends(get_container)],
) -> ProfileResponse:
    await container.rate_limiter.check(
        f"photo:{auth.user_id}", limit=10, window_seconds=3600
    )
    data = await photo.read(container.settings.max_photo_bytes + 1)
    return _profile(await container.update_own_photo.replace(auth.user_id, data))


@router.delete("/photo", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_photo(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    await container.update_own_photo.delete(auth.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_account(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    await container.delete_account.execute(auth.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
