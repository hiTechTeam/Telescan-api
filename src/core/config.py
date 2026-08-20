"""Environment-backed application settings.

Infrastructure clients are deliberately not constructed here.  Keeping settings
as plain values makes imports side-effect free and makes every external service
replaceable in tests.
"""

from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"

    mongo_username: str = "telescan"
    mongo_password: str = "telescan"
    mongo_host: str = "localhost"
    mongo_port: int = 27017
    mongo_dbname: str = "telescan_db"

    jwt_secret: str = Field(default="development-jwt-secret-change-me", min_length=32)
    link_code_hmac_secret: str = Field(
        default="development-link-secret-change-me", min_length=32
    )
    review_code_hmac_secret: str = Field(
        default="development-review-secret-change-me", min_length=32
    )
    bot_service_secret: str = Field(
        default="development-service-secret-change-me", min_length=32
    )
    moderation_service_secret: str = Field(
        default="development-moderation-secret-change-me", min_length=32
    )
    jwt_issuer: str = "telescan-api"
    access_token_ttl_seconds: int = Field(default=900, ge=300, le=3600)
    refresh_token_ttl_seconds: int = Field(default=2_592_000, ge=86_400)
    link_code_ttl_seconds: int = Field(default=600, ge=300, le=600)
    link_code_length: int = Field(default=8, ge=8, le=32)
    confirmation_ttl_seconds: int = Field(default=300, ge=60, le=600)

    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_endpoint_url: str = "https://s3.ru-7.storage.selcloud.ru"
    s3_public_base_url: str = "https://storage.invalid"
    s3_bucket_name: str = "profile-photos-telescan"
    max_photo_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)

    bot_internal_base_url: str = "http://telescan-bot-app:8080"
    internal_request_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    cors_origins: list[str] = Field(default_factory=list)
    enable_legacy_api: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def mongo_url(self) -> str:
        return (
            "mongodb://"
            f"{quote_plus(self.mongo_username)}:{quote_plus(self.mongo_password)}"
            f"@{self.mongo_host}:{self.mongo_port}/"
            "?authSource=admin&uuidRepresentation=standard"
        )

    @model_validator(mode="after")
    def reject_development_secrets_in_production(self) -> "Settings":
        if self.environment.lower() != "production":
            return self
        insecure = (
            self.jwt_secret.startswith("development-"),
            self.link_code_hmac_secret.startswith("development-"),
            self.review_code_hmac_secret.startswith("development-"),
            self.bot_service_secret.startswith("development-"),
            self.moderation_service_secret.startswith("development-"),
        )
        if any(insecure):
            raise ValueError("Production secrets must be explicitly configured")
        secrets = {
            self.jwt_secret,
            self.link_code_hmac_secret,
            self.review_code_hmac_secret,
            self.bot_service_secret,
            self.moderation_service_secret,
        }
        if len(secrets) != 5:
            raise ValueError("Production secrets must be distinct")
        if not self.cors_origins or "*" in self.cors_origins:
            raise ValueError("CORS_ORIGINS must be an explicit production allow-list")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

__all__ = ["Settings", "get_settings", "settings"]
