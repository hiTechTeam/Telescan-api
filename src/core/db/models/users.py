from typing import Optional
from beanie import Document, Indexed


__all__ = ["User"]


class User(Document):
    tg_id: int
    tg_name: Optional[str] = None
    tg_username: Optional[str] = None
    code: Optional[Indexed(str)] = None  # type: ignore
    photo_s3_link: Optional[str] = None

    class Settings:
        name = "users"
