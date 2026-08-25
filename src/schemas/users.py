from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProfileResponse(BaseModel):
    telescan_id: Annotated[UUID, Field(alias="telescanId")]
    name: str | None = None
    username: str | None = None
    bio: str | None = None
    photo_url: Annotated[str | None, Field(alias="photoUrl")] = None
    telegram_linked: Annotated[bool, Field(alias="telegramLinked")]
    model_config = ConfigDict(populate_by_name=True)


class ProfileUpdateRequest(BaseModel):
    bio: Annotated[str | None, Field(max_length=60)]


class LinkedAccountResponse(BaseModel):
    tokens: "TokenResponse"
    profile: ProfileResponse


from .auth import TokenResponse  # noqa: E402

LinkedAccountResponse.model_rebuild()


class TelegramLinkResponse(BaseModel):
    access: "AccessTokenResponse"
    profile: ProfileResponse


from .auth import AccessTokenResponse  # noqa: E402

TelegramLinkResponse.model_rebuild()
