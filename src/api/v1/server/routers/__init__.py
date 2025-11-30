"""Main router."""

# -- Imports

from fastapi import APIRouter
from .routing import code_router, users_router

# -- Exports

__all__ = ["main_router"]


main_router = APIRouter()
main_router.include_router(code_router)
main_router.include_router(users_router)
