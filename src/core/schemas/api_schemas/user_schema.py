"""User db model schema."""

# -- Imports

from pydantic import BaseModel
from typing import Optional

# -- Exports

__all__ = ["UserModelSchema"]

# --


class UserModelSchema(BaseModel):
    """User model schema"""

    tg_id: int
    tg_name: Optional[str] = None
    tg_username: Optional[str] = None
    code: Optional[str]
    is_active: bool = False

    ble_id: Optional[str] = None
    device_hash: Optional[str] = None
    device_type: Optional[str] = None
