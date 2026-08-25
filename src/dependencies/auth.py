from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.domain.entities import AuthContext
from src.domain.errors import InvalidToken, SessionRevoked

from .container import Container, get_container

bearer = HTTPBearer(auto_error=False)


async def get_current_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    container: Annotated[Container, Depends(get_container)],
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise InvalidToken()
    user_id, session_id = container.tokens.decode_access(credentials.credentials)
    session = await container.sessions.get_active(session_id, datetime.now(UTC))
    if session is None or str(getattr(session, "user_id")) != user_id:
        raise SessionRevoked()
    if await container.users.get_by_id(user_id) is None:
        raise InvalidToken()
    if await container.apple_identities.get_by_user_id(user_id) is None:
        raise InvalidToken()
    return AuthContext(user_id=user_id, session_id=session_id)
