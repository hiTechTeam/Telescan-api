"""Main router."""

# -- Imports

from fastapi import APIRouter
from .code_r import code_router

# -- Exports

__all__ = ["main_router"]


main_router = APIRouter()
main_router.include_router(code_router)
