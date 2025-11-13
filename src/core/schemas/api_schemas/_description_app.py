"""Description App."""

# -- Imports

from pydantic import BaseModel

# -- Exports

__all__ = ["DescriptionAppSchema"]

#


class DescriptionAppSchema(BaseModel):
    title: str = "Telescan-api"
    description: str = "Telescan app api."
    version: str = "0.0.0"
