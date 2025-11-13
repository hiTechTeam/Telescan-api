"""Schema configuration for constructing API endpoint paths."""

# -- Imports

from pydantic import BaseModel


# -- Exports

__all__ = ["ApiSchema"]

# --


class ApiSchema(BaseModel):
    """Configuration schema for base API endpoints."""

    v1: str = "/v1"
    code: str = "/code"

    @property
    def v1_code(self) -> str:
        """Full path for set data route."""

        return f"{self.v1}{self.code}"
