"""Response schemas."""

# -- Imports

from pydantic import BaseModel
from typing import Optional

# -- Exports

__all__ = ["GetUsernameByCode"]


class GetUsernameByCode(BaseModel):
    tg_name: Optional[str]
    tg_username: Optional[str]
