from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProfileResponse(BaseModel):
    telescan_id: UUID = Field(alias="telescanId")
    name: str | None = None
    username: str | None = None
    photo_url: str | None = Field(default=None, alias="photoUrl")
    model_config = ConfigDict(populate_by_name=True)


class LinkedAccountResponse(BaseModel):
    tokens: "TokenResponse"
    profile: ProfileResponse


from .auth import TokenResponse  # noqa: E402

LinkedAccountResponse.model_rebuild()
