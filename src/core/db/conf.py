"""MongoDB config."""

# -- Imports

from pydantic_settings import BaseSettings, SettingsConfigDict


# -- Exports

__all__ = ["mongo_db_url"]

# --


class MongoDBURL(BaseSettings):

    MONGO_USERNAME: str
    MONGO_PASSWORD: str
    MONGO_HOST: str
    MONGO_PORT: int
    MONGO_DBNAME: str

    dialect: str = "mongodb"
    localhost: str = "localhost"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    @property
    def get_MongoDB_URL(self) -> str:
        return f"{self.dialect}://{self.MONGO_USERNAME}:{self.MONGO_PASSWORD}@{self.MONGO_HOST}:{self.MONGO_PORT}"

    @property
    def get_MongoDB_Localhost(self) -> str:
        return f"{self.dialect}://{self.localhost}:{self.MONGO_PORT}"


mongo_db_url = MongoDBURL()  # type: ignore
