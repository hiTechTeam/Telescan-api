"""Code router."""

# -- Imports

import logging
from fastapi import APIRouter, status, HTTPException
from fastapi import Body
from src.core.config import settings
from src.core.schemas.request_schemas import (
    GetUserdataRequestByHashedCode,
    GetUserdataRequestByTGID,
)
from src.core.schemas.response_schemas import GetUserdataByCode, GetuserDataByTGID
from src.core.db.models import User

# -- Exports

__all__ = ["code_router", "users_router"]

# --

log = logging.getLogger(__name__)

code_router = APIRouter(prefix=settings.api.v1_code, tags=["code"])
users_router = APIRouter(prefix=settings.api.v1_users, tags=["users"])


@code_router.post(
    path="/",
    status_code=status.HTTP_200_OK,
    response_model=GetUserdataByCode,
    name="get-userdata-by-hashed_code",
)
async def get_userdata_by_code(payload: GetUserdataRequestByHashedCode = Body(...)):
    """Get userdata by code."""

    # hashed_code = hashlib.sha256(code.encode()).hexdigest()
    user = await User.find_one(User.code == payload.hashed_code)

    if not user or not user.tg_username:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    return GetUserdataByCode(
        tg_id=user.tg_id,
        tg_name=user.tg_name,
        tg_username=user.tg_username,
        photoS3URL=user.photo_s3_link,
    )


@users_router.post(
    path="/",
    status_code=status.HTTP_200_OK,
    response_model=GetuserDataByTGID,
    name="get-userdata-by-tg_id",
)
async def get_userdata_by_tg_id(payload: GetUserdataRequestByTGID = Body(...)):
    """Get userdata by tg_id"""

    user = await User.find_one(User.tg_id == int(payload.tg_id))

    if not user or not user.tg_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    return GetuserDataByTGID(
        tg_name=user.tg_name,
        tg_username=user.tg_username,
        photoS3URL=user.photo_s3_link,
    )
