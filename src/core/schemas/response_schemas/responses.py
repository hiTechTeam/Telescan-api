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
    tgId: int
    tgName: Optional[str]
    tgUsername: Optional[str]
    photoS3URL: Optional[str]


class GetuserDataByTGID(BaseModel):
    tgName: Optional[str]
    tgUsername: Optional[str]
    photoS3URL: Optional[str]


class UploadTelegramPhotoResponse(BaseModel):
    tgId: int
    photoS3URL: Optional[str] = None


class DeletePhotoResponse(BaseModel):
    tgId: int
    deleted: bool
