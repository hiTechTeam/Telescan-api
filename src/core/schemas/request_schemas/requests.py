"""Task schemas."""

# -- Imports

from pydantic import BaseModel, Field
from typing import Optional

# -- Exports

__all__ = [
    "GetUserdataRequestByHashedCode",
    "GetUserdataRequestByTGID",
    "SetUserPhotoRequestByTGID",
    "UpdateUserPhotoRequestByTGID",
    "DeleteUserAccountRequest",
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


class DeleteUserAccountRequest(BaseModel):
    tgId: int
    hashedCode: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
