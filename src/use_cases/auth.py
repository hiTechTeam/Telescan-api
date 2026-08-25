from datetime import UTC, datetime, timedelta
from uuid import UUID

from src.domain.entities import AccessToken, AuthTokens
from src.domain.errors import (
    AppleIdentityConflict,
    InvalidLinkCode,
    TelegramIdentityConflict,
    UserNotFound,
)
from src.domain.ports import (
    AppleIdentityRepositoryPort,
    AppleIdentityVerifierPort,
    LinkCodeRepositoryPort,
    ReviewCodeRepositoryPort,
    SessionRepositoryPort,
    UserRepositoryPort,
)
from src.domain.usernames import require_telegram_username
from src.services.codes import LinkCodeService
from src.services.sessions import SessionService


class LinkDevice:
    """Temporary Telegram-first authentication behind ENABLE_LEGACY_API."""

    def __init__(
        self,
        users: UserRepositoryPort,
        link_codes: LinkCodeRepositoryPort,
        sessions: SessionRepositoryPort,
        session_service: SessionService,
        codes: LinkCodeService,
        refresh_ttl_seconds: int,
        review_codes: ReviewCodeRepositoryPort | None = None,
        review_code_service: LinkCodeService | None = None,
    ) -> None:
        self._users = users
        self._link_codes = link_codes
        self._sessions = sessions
        self._session_service = session_service
        self._codes = codes
        self._refresh_ttl_seconds = refresh_ttl_seconds
        self._review_codes = review_codes
        self._review_code_service = review_code_service

    async def execute(
        self, code: str, device_id: UUID, now: datetime | None = None
    ) -> tuple[AuthTokens, object]:
        current_time = now or datetime.now(UTC)
        consumed = await self._link_codes.consume(
            self._codes.hash(code), device_id, current_time
        )
        if (
            consumed is None
            and self._review_codes is not None
            and self._review_code_service is not None
        ):
            consumed = await self._review_codes.consume(
                self._review_code_service.hash(code), device_id, current_time
            )
        if consumed is None:
            raise InvalidLinkCode()
        user_id = str(getattr(consumed, "user_id"))
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFound()
        require_telegram_username(getattr(user, "tg_username", None))
        session = await self._sessions.create_or_replace(
            user_id,
            device_id,
            current_time,
            current_time + timedelta(seconds=self._refresh_ttl_seconds),
        )
        return await self._session_service.issue(user_id, session, current_time), user


class SignInWithApple:
    def __init__(
        self,
        users: UserRepositoryPort,
        identities: AppleIdentityRepositoryPort,
        verifier: AppleIdentityVerifierPort,
        sessions: SessionRepositoryPort,
        session_service: SessionService,
        refresh_ttl_seconds: int,
    ) -> None:
        self._users = users
        self._identities = identities
        self._verifier = verifier
        self._sessions = sessions
        self._session_service = session_service
        self._refresh_ttl_seconds = refresh_ttl_seconds

    async def execute(
        self,
        identity_token: str,
        raw_nonce: str,
        device_id: UUID,
        name: str | None,
        now: datetime | None = None,
    ) -> tuple[AuthTokens, object]:
        current_time = now or datetime.now(UTC)
        claims = await self._verifier.verify(identity_token, raw_nonce)
        identity = await self._identities.get_by_subject(claims.subject)

        if identity is None:
            user = await self._users.create_unlinked()
            user_id = str(getattr(user, "id"))
            try:
                identity = await self._identities.create(
                    claims.subject,
                    user_id,
                    claims.email,
                    name,
                    current_time,
                )
            except AppleIdentityConflict:
                await self._users.delete(user_id)
                identity = await self._identities.get_by_subject(claims.subject)
                if identity is None:
                    raise

        user_id = str(getattr(identity, "user_id"))
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFound()
        session = await self._sessions.create_or_replace(
            user_id,
            device_id,
            current_time,
            current_time + timedelta(seconds=self._refresh_ttl_seconds),
        )
        return await self._session_service.issue(user_id, session, current_time), user


class LinkTelegramAccount:
    def __init__(
        self,
        users: UserRepositoryPort,
        identities: AppleIdentityRepositoryPort,
        link_codes: LinkCodeRepositoryPort,
        sessions: SessionRepositoryPort,
        session_service: SessionService,
        codes: LinkCodeService,
        review_codes: ReviewCodeRepositoryPort | None = None,
        review_code_service: LinkCodeService | None = None,
    ) -> None:
        self._users = users
        self._identities = identities
        self._link_codes = link_codes
        self._sessions = sessions
        self._session_service = session_service
        self._codes = codes
        self._review_codes = review_codes
        self._review_code_service = review_code_service

    async def execute(
        self,
        code: str,
        current_user_id: str,
        session_id: str,
        now: datetime | None = None,
    ) -> tuple[AccessToken, object]:
        current_time = now or datetime.now(UTC)
        session = await self._sessions.get_active(session_id, current_time)
        if session is None or str(getattr(session, "user_id")) != current_user_id:
            raise UserNotFound()
        device_id = getattr(session, "device_id")
        consumed = await self._link_codes.consume(
            self._codes.hash(code), device_id, current_time
        )
        if (
            consumed is None
            and self._review_codes is not None
            and self._review_code_service is not None
        ):
            consumed = await self._review_codes.consume(
                self._review_code_service.hash(code), device_id, current_time
            )
        if consumed is None:
            raise InvalidLinkCode()

        telegram_user_id = str(getattr(consumed, "user_id"))
        telegram_user = await self._users.get_by_id(telegram_user_id)
        if telegram_user is None:
            raise UserNotFound()
        require_telegram_username(getattr(telegram_user, "tg_username", None))

        current_identity = await self._identities.get_by_user_id(current_user_id)
        if current_identity is None:
            raise AppleIdentityConflict()
        existing_identity = await self._identities.get_by_user_id(telegram_user_id)
        if existing_identity is not None and str(
            getattr(existing_identity, "subject")
        ) != str(getattr(current_identity, "subject")):
            raise TelegramIdentityConflict()

        if telegram_user_id != current_user_id:
            await self._sessions.revoke_all(telegram_user_id, current_time)
            await self._identities.move_to_user(
                str(getattr(current_identity, "subject")),
                current_user_id,
                telegram_user_id,
                current_time,
            )
            session = await self._sessions.move_to_user(
                session_id, current_user_id, telegram_user_id
            )
            await self._users.delete(current_user_id)

        access = self._session_service.issue_access(
            telegram_user_id, session, current_time
        )
        return access, telegram_user


class RefreshSession:
    def __init__(self, sessions: SessionService) -> None:
        self._sessions = sessions

    async def execute(
        self, refresh_token: str, now: datetime | None = None
    ) -> AuthTokens:
        return await self._sessions.refresh(refresh_token, now or datetime.now(UTC))
