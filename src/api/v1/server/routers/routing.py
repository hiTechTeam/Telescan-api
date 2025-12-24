"""Code router."""

# -- Imports

import logging
import base64
from fastapi import APIRouter, status, HTTPException
from fastapi import Body
from src.core.config import settings
from src.core.schemas.request_schemas import (
    SetUserPhotoRequestByTGID,
    UpdateUserPhotoRequestByTGID,
)
from src.core.schemas.response_schemas import (
    GetUserdataByCode,
    GetuserDataByTGID,
    UploadTelegramPhotoResponse,
)
from src.core.db.models import User
from src.core.config import settings as s

# -- Exports

__all__ = [
    "code_router",
    "users_router",
]

# --

log = logging.getLogger(__name__)

code_router = APIRouter(prefix=settings.api.v1_code, tags=["code"])
users_router = APIRouter(prefix=settings.api.v1_users, tags=["users"])


@code_router.get(
    path="/",
    status_code=status.HTTP_200_OK,
    response_model=GetUserdataByCode,
    name="get-userdata-by-hashed_code",
)
async def get_userdata_by_code(hashed_code: str):
    """Get userdata by code."""

    # hashed_code = hashlib.sha256(code.encode()).hexdigest()
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
async def get_userdata_by_tg_id(tg_id: int):
    """Get userdata by tg_id"""

    user = await User.find_one(User.tg_id == tg_id)

    if not user or not user.tg_id:
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
):
    """
    Upload user photo to S3 and update user record.
    """

    tg_id = payload.tg_id
    img = payload.img

    # Validate user exists
    user = await User.find_one(User.tg_id == tg_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    object_name = f"{tg_id}.jpg"

    try:
        photo_url = await s.s3_client.upload_photo(
            img=img,
            object_name=object_name,
        )
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Failed to download or upload photo",
        )

    user.photo_s3_link = photo_url
    await user.save()

    return UploadTelegramPhotoResponse(
        tgId=tg_id,
        photoS3URL=photo_url,
    )


@users_router.post(
    path="/update-photo",
    status_code=status.HTTP_200_OK,
    response_model=UploadTelegramPhotoResponse,
)
async def update_telegram_photo(payload: UpdateUserPhotoRequestByTGID):

    user = await User.find_one(User.tg_id == payload.tg_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.img is None:
        user.photo_s3_link = None
        await user.save()

        return UploadTelegramPhotoResponse(
            tgId=user.tg_id,
            photoS3URL=None,
        )

    try:
        img_bytes = base64.b64decode(payload.img)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 image")

    object_name = f"{payload.tg_id}.jpg"

    photo_url = await s.s3_client.upload_photo(
        img=img_bytes,
        object_name=object_name,
    )

    user.photo_s3_link = photo_url
    await user.save()

    return UploadTelegramPhotoResponse(
        tgId=user.tg_id,
        photoS3URL=photo_url,
    )
