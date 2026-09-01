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
    return await _resolve_current_auth(credentials, container, allow_merge_resume=False)


async def get_current_auth_for_merge(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    container: Annotated[Container, Depends(get_container)],
) -> AuthContext:
    return await _resolve_current_auth(credentials, container, allow_merge_resume=True)


async def _resolve_current_auth(
    credentials: HTTPAuthorizationCredentials | None,
    container: Container,
    *,
    allow_merge_resume: bool,
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise InvalidToken()
    user_id, session_id = container.tokens.decode_access(credentials.credentials)
    session = await container.sessions.get_active(session_id, datetime.now(UTC))
    if session is None:
        raise SessionRevoked()
    session_user_id = str(getattr(session, "user_id"))
    resolved_user_id = user_id
    merge = None
    account_merges = getattr(container, "account_merges", None)
    if account_merges is not None:
        merge = await account_merges.get_by_source(user_id)
    account_operation_guard = getattr(container, "account_operation_guard", None)
    if account_operation_guard is not None and await account_operation_guard.is_fenced(
        session_user_id
    ):
        resumable_source_merge = (
            allow_merge_resume
            and merge is not None
            and str(getattr(merge, "source_user_id")) == user_id
        )
        if not resumable_source_merge:
            raise SessionRevoked()
    if session_user_id != user_id:
        if merge is None or str(getattr(merge, "target_user_id")) != session_user_id:
            raise SessionRevoked()
        resolved_user_id = session_user_id
    if await container.users.get_by_id(resolved_user_id) is None:
        raise InvalidToken()
    identity = await container.apple_identities.get_by_user_id(resolved_user_id)
    settings = getattr(container, "settings", None)
    legacy_enabled = getattr(
        settings,
        "legacy_api_active",
        getattr(settings, "enable_legacy_api", False),
    )
    merge_in_progress = merge is not None and resolved_user_id == user_id
    if identity is None and not legacy_enabled and not merge_in_progress:
        raise InvalidToken()
    return AuthContext(user_id=resolved_user_id, session_id=session_id)
