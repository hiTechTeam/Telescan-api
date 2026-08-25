import secrets
from datetime import datetime

from src.domain.entities import AccessToken, AuthTokens
from src.domain.errors import InvalidToken, RefreshTokenReused, SessionRevoked
from src.domain.ports import SessionRepositoryPort
from src.infrastructure.jwt import TokenService


class SessionService:
    def __init__(
        self,
        sessions: SessionRepositoryPort,
        tokens: TokenService,
    ) -> None:
        self._sessions = sessions
        self._tokens = tokens

    async def issue(self, user_id: str, session: object, now: datetime) -> AuthTokens:
        session_id = str(getattr(session, "id"))
        refresh = self._tokens.issue_refresh(session_id)
        await self._sessions.set_refresh_hash(
            session_id, self._tokens.hash_refresh(refresh), now
        )
        return AuthTokens(
            access_token=self._tokens.issue_access(user_id, session_id, now),
            refresh_token=refresh,
            expires_in=self._tokens.access_ttl_seconds,
        )

    def issue_access(self, user_id: str, session: object, now: datetime) -> AccessToken:
        session_id = str(getattr(session, "id"))
        return AccessToken(
            access_token=self._tokens.issue_access(user_id, session_id, now),
            expires_in=self._tokens.access_ttl_seconds,
        )

    async def refresh(self, refresh_token: str, now: datetime) -> AuthTokens:
        session_id = self._tokens.refresh_session_id(refresh_token)
        session = await self._sessions.get_active(session_id, now)
        if session is None:
            raise SessionRevoked()

        presented_hash = self._tokens.hash_refresh(refresh_token)
        stored_hash = str(getattr(session, "refresh_token_hash"))
        if not secrets.compare_digest(stored_hash, presented_hash):
            await self._sessions.revoke(session_id, now)
            raise RefreshTokenReused()

        replacement = self._tokens.issue_refresh(session_id)
        replacement_hash = self._tokens.hash_refresh(replacement)
        rotated = await self._sessions.rotate_refresh_hash(
            session_id, presented_hash, replacement_hash, now
        )
        if not rotated:
            await self._sessions.revoke(session_id, now)
            raise RefreshTokenReused()

        user_id = str(getattr(session, "user_id"))
        if not user_id:
            raise InvalidToken()
        return AuthTokens(
            access_token=self._tokens.issue_access(user_id, session_id, now),
            refresh_token=replacement,
            expires_in=self._tokens.access_ttl_seconds,
        )
