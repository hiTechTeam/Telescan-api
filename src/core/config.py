"""Environment-backed application settings.

Infrastructure clients are deliberately not constructed here.  Keeping settings
as plain values makes imports side-effect free and makes every external service
replaceable in tests.
"""

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from urllib.parse import quote_plus, urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return (
        not normalized
        or normalized.startswith(("development-", "replace-", "change-me"))
        or normalized in {"password", "secret", "changeme"}
    )


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
    apple_bundle_id: str = "hiTeam.TelescaniOS"
    apple_keys_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
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
    maintenance_interval_seconds: int = Field(default=60, ge=10, le=3600)
    cors_origins: list[str] = Field(default_factory=list)
    enable_telegram_first_auth: bool = False
    enable_legacy_api: bool = False
    legacy_api_expires_at: datetime | None = None
    production_legacy_risk_accepted: bool = False
    require_moderation_revision: bool = False
    moderation_revision_compatibility_expires_at: datetime | None = None

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

    @property
    def legacy_api_active(self) -> bool:
        expires_at = self.legacy_api_expires_at
        if not self.enable_legacy_api or expires_at is None:
            return False
        if expires_at.tzinfo is None:
            return False
        return expires_at.astimezone(UTC) > datetime.now(UTC)

    @property
    def telegram_first_auth_active(self) -> bool:
        """Allow modern one-time bot codes without exposing legacy /v1 routes."""
        return self.enable_telegram_first_auth or self.legacy_api_active

    @model_validator(mode="after")
    def reject_development_secrets_in_production(self) -> "Settings":
        if self.environment.lower() != "production":
            return self
        if self.enable_legacy_api:
            raise ValueError("The legacy API is forbidden in production")
        if not self.require_moderation_revision:
            compatibility_until = self.moderation_revision_compatibility_expires_at
            if compatibility_until is None or compatibility_until.tzinfo is None:
                raise ValueError(
                    "Production moderation CAS requires a revision or an explicit "
                    "compatibility deadline"
                )
            remaining = compatibility_until.astimezone(UTC) - datetime.now(UTC)
            if remaining <= timedelta(0) or remaining > timedelta(days=7):
                raise ValueError(
                    "Moderation revision compatibility window must be active and "
                    "cannot exceed 7 days"
                )
        insecure = tuple(
            _is_placeholder(secret)
            for secret in (
                self.jwt_secret,
                self.link_code_hmac_secret,
                self.review_code_hmac_secret,
                self.bot_service_secret,
                self.moderation_service_secret,
            )
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
        if "*" in self.cors_origins:
            raise ValueError("CORS_ORIGINS may not contain a wildcard in production")
        for origin in self.cors_origins:
            parsed_origin = urlsplit(origin)
            if (
                parsed_origin.scheme != "https"
                or not parsed_origin.hostname
                or parsed_origin.username is not None
                or parsed_origin.password is not None
                or parsed_origin.path not in {"", "/"}
                or parsed_origin.query
                or parsed_origin.fragment
            ):
                raise ValueError(
                    "CORS_ORIGINS entries must be credential-free HTTPS origins"
                )
        if self.mongo_host != "mongo" or self.mongo_port != 27017:
            raise ValueError("Production MongoDB must use the private Docker route")
        if self.mongo_dbname.lower() in {"admin", "config", "local"}:
            raise ValueError("MONGO_DBNAME may not be a MongoDB system database")
        if (
            self.mongo_username.strip().lower()
            in {"telescan", "root", "admin", "administrator"}
            or _is_placeholder(self.mongo_username)
            or _is_placeholder(self.mongo_password)
            or len(self.mongo_password) < 24
        ):
            raise ValueError("Production MongoDB credentials must be explicit")
        if (
            any(
                _is_placeholder(value)
                for value in (self.s3_access_key, self.s3_secret_key)
            )
            or len(self.s3_access_key) < 16
            or len(self.s3_secret_key) < 32
        ):
            raise ValueError("Production S3 credentials may not be placeholders")
        for label, raw_url in (
            ("S3_ENDPOINT_URL", self.s3_endpoint_url),
            ("S3_PUBLIC_BASE_URL", self.s3_public_base_url),
        ):
            parsed = urlsplit(raw_url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError(f"{label} must be a credential-free HTTPS origin")
        endpoint_host = urlsplit(self.s3_endpoint_url).hostname
        endpoint = urlsplit(self.s3_endpoint_url)
        if (
            endpoint_host != "s3.ru-7.storage.selcloud.ru"
            or endpoint.port not in {None, 443}
            or endpoint.path not in {"", "/"}
            or endpoint.query
            or endpoint.fragment
        ):
            raise ValueError("Production S3 endpoint is not an approved provider host")
        if self.s3_bucket_name != "profile-photos-telescan":
            raise ValueError("Production S3 bucket is not approved")
        public_base = urlsplit(self.s3_public_base_url)
        if (
            public_base.hostname != "b16a45ef-34c8-400e-8e9f-c71d081ad546.selstorage.ru"
            or public_base.port not in {None, 443}
            or public_base.path not in {"", "/"}
            or public_base.query
            or public_base.fragment
        ):
            raise ValueError("Production S3 public base is not an approved host")
        bot_url = urlsplit(self.bot_internal_base_url)
        if (
            bot_url.scheme != "http"
            or bot_url.hostname != "telescan-bot-app"
            or bot_url.port != 8080
            or bot_url.username is not None
            or bot_url.password is not None
            or bot_url.path not in {"", "/"}
        ):
            raise ValueError(
                "Production bot callback must use the private Docker origin"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

__all__ = ["Settings", "get_settings", "settings"]
