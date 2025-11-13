"""Application configuration module."""

# -- Imports

from pydantic_settings import BaseSettings
from src.core.schemas.api_schemas import DescriptionAppSchema, ApiSchema


# -- Exports

__all__ = ["settings"]

# --


class Settings(BaseSettings):
    """Main application settings."""

    mongo_client_name: str = "telescan_db"
    _description: DescriptionAppSchema = DescriptionAppSchema()
    api: ApiSchema = ApiSchema()


settings = Settings()
