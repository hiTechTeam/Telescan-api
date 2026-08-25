from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AppleSignInRequest(BaseModel):
    identity_token: Annotated[str, Field(alias="identityToken", min_length=20)]
    nonce: Annotated[str, Field(min_length=16, max_length=256)]
    device_id: Annotated[UUID, Field(alias="deviceId")]
    name: Annotated[str | None, Field(max_length=120)] = None
    model_config = ConfigDict(populate_by_name=True)


class TelegramLinkRequest(BaseModel):
    code: str = Field(min_length=8, max_length=64)
    model_config = ConfigDict(populate_by_name=True)


class RefreshRequest(BaseModel):
    refresh_token: Annotated[
        str, Field(alias="refreshToken", min_length=48, max_length=512)
    ]
    model_config = ConfigDict(populate_by_name=True)


class TokenResponse(BaseModel):
    access_token: Annotated[str, Field(alias="accessToken")]
    refresh_token: Annotated[str, Field(alias="refreshToken")]
    token_type: Annotated[str, Field(alias="tokenType")] = "bearer"
    expires_in: Annotated[int, Field(alias="expiresIn")]
    model_config = ConfigDict(populate_by_name=True)


class AccessTokenResponse(BaseModel):
    access_token: Annotated[str, Field(alias="accessToken")]
    token_type: Annotated[str, Field(alias="tokenType")] = "bearer"
    expires_in: Annotated[int, Field(alias="expiresIn")]
    model_config = ConfigDict(populate_by_name=True)
