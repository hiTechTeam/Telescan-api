import secrets
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.domain.errors import InvalidToken

from .container import Container, get_container

internal_bearer = HTTPBearer(auto_error=False)


async def require_internal_service(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(internal_bearer)
    ],
    container: Annotated[Container, Depends(get_container)],
) -> None:
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not secrets.compare_digest(
            credentials.credentials, container.settings.bot_service_secret
        )
    ):
        raise InvalidToken()
