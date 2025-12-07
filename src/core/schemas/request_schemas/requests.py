"""Task schemas."""

# -- Imports

from pydantic import BaseModel
from typing import Optional

# -- Exports

__all__ = [
    "GetUserdataRequestByHashedCode",
    "GetUserdataRequestByTGID",
    "SetUserPhotoRequestByTGID",
]


class GetUserdataRequestByHashedCode(BaseModel):
    hashed_code: Optional[str]


class GetUserdataRequestByTGID(BaseModel):
    tg_id: int


class SetUserPhotoRequestByTGID(BaseModel):
    tg_id: int
    img: bytes
