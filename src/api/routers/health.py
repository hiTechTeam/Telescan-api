from fastapi import APIRouter, status
from fastapi.responses import ORJSONResponse

from src.infrastructure.mongodb import database_ready

router = APIRouter(tags=["health"], include_in_schema=False)


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", response_model=None)
async def readiness() -> dict[str, str] | ORJSONResponse:
    if await database_ready():
        return {"status": "ok"}
    return ORJSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "unavailable"},
    )


__all__ = ["router"]
