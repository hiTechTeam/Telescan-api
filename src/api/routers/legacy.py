from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from src.dependencies.container import Container, get_container
from src.schemas.legacy import (
    LegacyDeleteRequest,
    LegacyPhotoRequest,
    LegacyProfileResponse,
)

router = APIRouter(prefix="/v1", tags=["legacy"], include_in_schema=False)


def _enabled(container: Container) -> None:
    if not container.settings.enable_legacy_api:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


def _response(user: object, include_id: bool = False) -> LegacyProfileResponse:
    return LegacyProfileResponse(
        tg_id=getattr(user, "tg_id") if include_id else None,
        tg_name=getattr(user, "tg_name", None),
        tg_username=getattr(user, "tg_username", None),
        photo_url=getattr(user, "photo_s3_link", None),
    )


@router.get("/code/", response_model=LegacyProfileResponse)
async def legacy_by_code(
    hashed_code: str,
    container: Annotated[Container, Depends(get_container)],
) -> LegacyProfileResponse:
    _enabled(container)
    return _response(await container.legacy.by_code(hashed_code), include_id=True)


@router.get("/users/", response_model=LegacyProfileResponse)
async def legacy_by_telegram_id(
    tg_id: int,
    container: Annotated[Container, Depends(get_container)],
) -> LegacyProfileResponse:
    _enabled(container)
    return _response(await container.legacy.by_telegram_id(tg_id))


@router.post("/users/upload-photo", response_model=LegacyProfileResponse)
async def legacy_upload_photo(
    payload: LegacyPhotoRequest,
    container: Annotated[Container, Depends(get_container)],
) -> LegacyProfileResponse:
    _enabled(container)
    if payload.img is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
    return _response(await container.legacy.replace_photo(payload.tg_id, payload.img))


@router.post("/users/update-photo", response_model=LegacyProfileResponse)
async def legacy_update_photo(
    payload: LegacyPhotoRequest,
    container: Annotated[Container, Depends(get_container)],
) -> LegacyProfileResponse:
    _enabled(container)
    user = (
        await container.legacy.delete_photo(payload.tg_id)
        if payload.img is None
        else await container.legacy.replace_photo(payload.tg_id, payload.img)
    )
    return _response(user)


@router.delete("/users/", status_code=status.HTTP_204_NO_CONTENT)
async def legacy_delete_account(
    payload: LegacyDeleteRequest,
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    _enabled(container)
    await container.legacy.delete(payload.tg_id, payload.hashed_code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
