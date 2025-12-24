"""Task schemas."""

# -- Imports

from pydantic import BaseModel
from typing import Optional

# -- Exports

__all__ = [
    "GetUserdataRequestByHashedCode",
    "GetUserdataRequestByTGID",
    "SetUserPhotoRequestByTGID",
    "UpdateUserPhotoRequestByTGID",
]


class GetUserdataRequestByHashedCode(BaseModel):
    hashed_code: Optional[str]


class GetUserdataRequestByTGID(BaseModel):
    tgId: int


class SetUserPhotoRequestByTGID(BaseModel):
    tgId: int
    img: bytes


class UpdateUserPhotoRequestByTGID(BaseModel):
    tgId: int
    img: Optional[str] = None
