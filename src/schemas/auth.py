from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LinkRequest(BaseModel):
    code: str = Field(min_length=8, max_length=64)
    device_id: UUID = Field(alias="deviceId")
    model_config = ConfigDict(populate_by_name=True)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(alias="refreshToken", min_length=48, max_length=512)
    model_config = ConfigDict(populate_by_name=True)


class TokenResponse(BaseModel):
    access_token: str = Field(alias="accessToken")
    refresh_token: str = Field(alias="refreshToken")
    token_type: str = Field(default="bearer", alias="tokenType")
    expires_in: int = Field(alias="expiresIn")
    model_config = ConfigDict(populate_by_name=True)
