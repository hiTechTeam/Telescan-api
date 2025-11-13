from typing import Optional
from beanie import Document, Indexed


__all__ = ["User"]


class User(Document):
    tg_id: int
    tg_name: Optional[str] = None
    tg_username: Optional[str] = None
    code: Optional[Indexed(str)]  # type: ignore
    is_active: bool = False

    ble_id: Optional[Indexed(str)] = None  # type: ignore
    device_hash: Optional[Indexed(str)] = None  # type: ignore
    device_type: Optional[str] = None  # type: ignore

    class Settings:
        name = "users"
