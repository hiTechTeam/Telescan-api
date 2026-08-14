from datetime import UTC, datetime, timedelta
from uuid import UUID

from src.domain.entities import AuthTokens
from src.domain.errors import InvalidLinkCode, UserNotFound
from src.domain.ports import LinkCodeRepositoryPort, SessionRepositoryPort, UserRepositoryPort
from src.services.codes import LinkCodeService
from src.services.sessions import SessionService


class LinkDevice:
    def __init__(
        self,
        users: UserRepositoryPort,
        link_codes: LinkCodeRepositoryPort,
        sessions: SessionRepositoryPort,
        session_service: SessionService,
        codes: LinkCodeService,
        refresh_ttl_seconds: int,
    ) -> None:
        self._users = users
        self._link_codes = link_codes
        self._sessions = sessions
        self._session_service = session_service
        self._codes = codes
        self._refresh_ttl_seconds = refresh_ttl_seconds

    async def execute(
        self, code: str, device_id: UUID, now: datetime | None = None
    ) -> tuple[AuthTokens, object]:
        current_time = now or datetime.now(UTC)
        consumed = await self._link_codes.consume(
            self._codes.hash(code), device_id, current_time
        )
        if consumed is None:
            raise InvalidLinkCode()
        user_id = str(getattr(consumed, "user_id"))
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFound()
        session = await self._sessions.create_or_replace(
            user_id,
            device_id,
            current_time,
            current_time + timedelta(seconds=self._refresh_ttl_seconds),
        )
        tokens = await self._session_service.issue(user_id, session, current_time)
        return tokens, user


class RefreshSession:
    def __init__(self, sessions: SessionService) -> None:
        self._sessions = sessions

    async def execute(
        self, refresh_token: str, now: datetime | None = None
    ) -> AuthTokens:
        return await self._sessions.refresh(refresh_token, now or datetime.now(UTC))
