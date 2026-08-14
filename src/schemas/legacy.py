from pydantic import BaseModel, ConfigDict, Field


class LegacyPhotoRequest(BaseModel):
    tg_id: int = Field(alias="tgId")
    img: str | None = None
    model_config = ConfigDict(populate_by_name=True)


class LegacyDeleteRequest(BaseModel):
    tg_id: int = Field(alias="tgId")
    hashed_code: str = Field(alias="hashedCode", min_length=64, max_length=64)
    model_config = ConfigDict(populate_by_name=True)


class LegacyProfileResponse(BaseModel):
    tg_id: int | None = Field(default=None, alias="tgId")
    tg_name: str | None = Field(default=None, alias="tgName")
    tg_username: str | None = Field(default=None, alias="tgUsername")
    photo_url: str | None = Field(default=None, alias="photoS3URL")
    model_config = ConfigDict(populate_by_name=True)
