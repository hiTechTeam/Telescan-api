from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class LegacyPhotoRequest(BaseModel):
    tg_id: Annotated[int, Field(alias="tgId")]
    img: str | None = None
    model_config = ConfigDict(populate_by_name=True)


class LegacyDeleteRequest(BaseModel):
    tg_id: Annotated[int, Field(alias="tgId")]
    hashed_code: Annotated[str, Field(alias="hashedCode", min_length=64, max_length=64)]
    model_config = ConfigDict(populate_by_name=True)


class LegacyProfileResponse(BaseModel):
    tg_id: Annotated[int | None, Field(alias="tgId")] = None
    tg_name: Annotated[str | None, Field(alias="tgName")] = None
    tg_username: Annotated[str | None, Field(alias="tgUsername")] = None
    photo_url: Annotated[str | None, Field(alias="photoS3URL")] = None
    model_config = ConfigDict(populate_by_name=True)
