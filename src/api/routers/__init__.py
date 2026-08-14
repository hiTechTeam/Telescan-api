from fastapi import APIRouter

from .auth import router as auth_router
from .internal import router as internal_router
from .legacy import router as legacy_router
from .profiles import router as profiles_router
from .users import router as users_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(users_router)
router.include_router(profiles_router)
router.include_router(internal_router)
router.include_router(legacy_router)

__all__ = ["router"]
