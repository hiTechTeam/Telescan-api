"""Code router."""

# -- Imports

import logging
from fastapi import APIRouter, status, HTTPException
from fastapi import Body
from src.core.config import settings
from src.core.schemas.response_schemas import GetUsernameByCode
from src.core.schemas.request_schemas import GetUsernameRequest
from src.core.db.models import User

# -- Exports

__all__ = ["code_router"]

# --

log = logging.getLogger(__name__)

code_router = APIRouter(prefix=settings.api.v1_code, tags=["code"])


@code_router.post(
    path="/",
    status_code=status.HTTP_200_OK,
    response_model=GetUsernameByCode,
    name="get-username-by-hashed_code",
)
async def get_username_by_code(payload: GetUsernameRequest = Body(...)):
    """Get telegram username by code."""

    # hashed_code = hashlib.sha256(code.encode()).hexdigest()
    user = await User.find_one(User.code == payload.hashed_code)

    if not user or not user.tg_username:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    return GetUsernameByCode(tg_name=user.tg_name, tg_username=user.tg_username)
