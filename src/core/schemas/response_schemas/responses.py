"""Response schemas."""

# -- Imports

from pydantic import BaseModel
from typing import Optional

# -- Exports

__all__ = [
    "GetUserdataByCode",
    "GetuserDataByTGID",
    "UploadTelegramPhotoResponse",
    "DeletePhotoResponse",
]


class GetUserdataByCode(BaseModel):
    tg_id: int
    tg_name: Optional[str]
    tg_username: Optional[str]
    photoS3URL: Optional[str]


class GetuserDataByTGID(BaseModel):
    tg_name: Optional[str]
    tg_username: Optional[str]
    photoS3URL: Optional[str]


class UploadTelegramPhotoResponse(BaseModel):
    tg_id: int
    photoS3URL: Optional[str] = None


class DeletePhotoResponse(BaseModel):
    tg_id: int
    deleted: bool
