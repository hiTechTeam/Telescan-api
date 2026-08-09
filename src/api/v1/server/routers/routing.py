"""Code and user routers."""

import base64
import binascii
import logging
from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException, status

from src.core.config import settings
from src.core.config import settings as s
from src.core.db.models import User
from src.core.schemas.request_schemas import (
    SetUserPhotoRequestByTGID,
    UpdateUserPhotoRequestByTGID,
)
from src.core.schemas.response_schemas import (
    GetUserdataByCode,
    GetuserDataByTGID,
    UploadTelegramPhotoResponse,
)

__all__ = [
    "code_router",
    "users_router",
]

log = logging.getLogger(__name__)

code_router = APIRouter(
    prefix=settings.api.v1_code,
    tags=["code"],
)

users_router = APIRouter(
    prefix=settings.api.v1_users,
    tags=["users"],
)


def decode_base64_image(value: str | bytes) -> bytes:
    try:
        image_bytes = base64.b64decode(
            value,
            validate=True,
        )
    except (
        binascii.Error,
        TypeError,
        ValueError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid base64 image",
        ) from error

    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image is empty",
        )

    return image_bytes


async def replace_user_photo(
    user: User,
    tg_id: int,
    image_bytes: bytes,
) -> str:
    old_photo_url = user.photo_s3_link

    object_name = f"users/{tg_id}/{uuid4().hex}.jpg"

    try:
        photo_url = await s.s3_client.upload_photo(
            img=image_bytes,
            object_name=object_name,
        )
    except Exception as error:
        log.exception(
            "Failed to upload profile photo for user %s",
            tg_id,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload photo",
        ) from error

    try:
        user.photo_s3_link = photo_url
        await user.save()
    except Exception as error:
        try:
            await s.s3_client.delete_file(object_name)
        except Exception:
            log.exception(
                "Failed to clean up uploaded object %s",
                object_name,
            )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save photo URL",
        ) from error

    if old_photo_url and old_photo_url != photo_url:
        try:
            await s.s3_client.delete_by_public_url(old_photo_url)
        except Exception:
            log.exception(
                "Failed to delete old profile photo for user %s",
                tg_id,
            )

    return photo_url


async def delete_user_photo(user: User) -> None:
    old_photo_url = user.photo_s3_link

    user.photo_s3_link = None
    await user.save()

    if old_photo_url:
        try:
            await s.s3_client.delete_by_public_url(old_photo_url)
        except Exception:
            log.exception(
                "Failed to delete profile photo from S3 for user %s",
                user.tg_id,
            )


@code_router.get(
    path="/",
    status_code=status.HTTP_200_OK,
    response_model=GetUserdataByCode,
    name="get-userdata-by-hashed_code",
)
async def get_userdata_by_code(
    hashed_code: str,
) -> GetUserdataByCode:
    user = await User.find_one(User.code == hashed_code)

    if not user or not user.tg_username:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    return GetUserdataByCode(
        tgId=user.tg_id,
        tgName=user.tg_name,
        tgUsername=user.tg_username,
        photoS3URL=user.photo_s3_link,
    )


@users_router.get(
    path="/",
    status_code=status.HTTP_200_OK,
    response_model=GetuserDataByTGID,
    name="get-userdata-by-tg_id",
)
async def get_userdata_by_tg_id(
    tg_id: int,
) -> GetuserDataByTGID:
    user = await User.find_one(User.tg_id == tg_id)

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    return GetuserDataByTGID(
        tgName=user.tg_name,
        tgUsername=user.tg_username,
        photoS3URL=user.photo_s3_link,
    )


@users_router.post(
    path="/upload-photo",
    status_code=status.HTTP_200_OK,
    response_model=UploadTelegramPhotoResponse,
    name="upload-photo",
)
async def upload_telegram_photo_handler(
    payload: SetUserPhotoRequestByTGID = Body(...),
) -> UploadTelegramPhotoResponse:
    user = await User.find_one(User.tg_id == payload.tgId)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    image_bytes = decode_base64_image(payload.img)

    photo_url = await replace_user_photo(
        user=user,
        tg_id=payload.tgId,
        image_bytes=image_bytes,
    )

    return UploadTelegramPhotoResponse(
        tgId=payload.tgId,
        photoS3URL=photo_url,
    )


@users_router.post(
    path="/update-photo",
    status_code=status.HTTP_200_OK,
    response_model=UploadTelegramPhotoResponse,
    name="update-photo",
)
async def update_telegram_photo(
    payload: UpdateUserPhotoRequestByTGID,
) -> UploadTelegramPhotoResponse:
    user = await User.find_one(User.tg_id == payload.tgId)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if payload.img is None:
        try:
            await delete_user_photo(user)
        except Exception as error:
            log.exception(
                "Failed to delete profile photo for user %s",
                payload.tgId,
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete photo",
            ) from error

        return UploadTelegramPhotoResponse(
            tgId=user.tg_id,
            photoS3URL=None,
        )

    image_bytes = decode_base64_image(payload.img)

    photo_url = await replace_user_photo(
        user=user,
        tg_id=payload.tgId,
        image_bytes=image_bytes,
    )

    return UploadTelegramPhotoResponse(
        tgId=user.tg_id,
        photoS3URL=photo_url,
    )
