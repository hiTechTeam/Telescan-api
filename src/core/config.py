"""Application configuration module."""

# -- Imports

import os
from pydantic_settings import BaseSettings
from src.core.schemas.api_schemas import DescriptionAppSchema, ApiSchema
from src.core.s3 import S3Client
from dotenv import load_dotenv

load_dotenv()

# -- Exports

__all__ = ["settings"]

# --

S3AccessKey: str = os.getenv("TelescanS3AccessKey")  # type: ignore
S3SecretKey: str = os.getenv("TelescanS3SecretKey")  # type: ignore
S3EndpointURL_telescan_photos: str = "https://s3.ru-7.storage.selcloud.ru"
S3BucketName: str = "profile-photos-telescan"


class Settings(BaseSettings):
    """Main application settings."""

    mongo_client_name: str = "telescan_db"
    _description: DescriptionAppSchema = DescriptionAppSchema()
    api: ApiSchema = ApiSchema()
    s3_client = S3Client(
        access_key=S3AccessKey,
        secret_key=S3SecretKey,
        endpoint_url=S3EndpointURL_telescan_photos,
        bucket_name=S3BucketName,
    )

    class Config:
        ignored_types = (S3Client,)


settings = Settings()
