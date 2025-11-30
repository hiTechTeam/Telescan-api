"""Task schemas."""

# -- Imports

from pydantic import BaseModel
from typing import Optional

# -- Exports

__all__ = [
    "GetUserdataRequestByHashedCode",
    "GetUserdataRequestByTGID",
]


class GetUserdataRequestByHashedCode(BaseModel):
    hashed_code: Optional[str]


class GetUserdataRequestByTGID(BaseModel):
    tg_id: int
