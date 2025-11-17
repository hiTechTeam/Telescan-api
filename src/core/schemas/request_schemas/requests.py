"""Task schemas."""

# -- Imports

from pydantic import BaseModel
from typing import Optional

# -- Exports

__all__ = ["GetUsernameRequest"]


class GetUsernameRequest(BaseModel):
    hashed_code: Optional[str]
