"""Task schemas."""

# -- Imports

from pydantic import BaseModel
from typing import Optional

# -- Exports

__all__ = ["GetUsernameByCode"]


class GetUsernameByCode(BaseModel):
    tg_username: Optional[str]
