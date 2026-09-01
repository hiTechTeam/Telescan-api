from datetime import UTC, datetime, timedelta
from uuid import UUID

from src.domain.entities import AccessToken, AuthTokens
from src.domain.enums import LinkCodeStatus
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
from src.services.account_merges import AccountMergeService
from src.services.account_operations import AccountOperationGuard
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
        account_operations: AccountOperationGuard | None = None,
    ) -> None:
        self._users = users
        self._link_codes = link_codes
        self._sessions = sessions
        self._session_service = session_service
        self._codes = codes
        self._refresh_ttl_seconds = refresh_ttl_seconds
        self._review_codes = review_codes
        self._review_code_service = review_code_service
        self._account_operations = account_operations

    async def execute(
        self, code: str, device_id: UUID, now: datetime | None = None
    ) -> tuple[AuthTokens, object]:
        current_time = now or datetime.now(UTC)
        candidate = await self._link_codes.find_for_link(
            self._codes.hash(code), device_id, current_time
        )
        candidate_repository: LinkCodeRepositoryPort | ReviewCodeRepositoryPort = (
            self._link_codes
        )
        if (
            candidate is None
            and self._review_codes is not None
            and self._review_code_service is not None
        ):
            candidate = await self._review_codes.find_for_link(
                self._review_code_service.hash(code), device_id, current_time
            )
            candidate_repository = self._review_codes
        if candidate is None:
            raise InvalidLinkCode()
        user_id = str(getattr(candidate, "user_id"))
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFound()
        require_telegram_username(getattr(user, "tg_username", None))

        async def consume_and_create_session(*, admitted: bool) -> AuthTokens:
            if getattr(candidate, "status") == LinkCodeStatus.ISSUED:
                consumed = await candidate_repository.consume(
                    str(getattr(candidate, "code_hash")), device_id, current_time
                )
                if consumed is None:
                    raise InvalidLinkCode()
            session = await self._sessions.create_or_replace(
                user_id,
                device_id,
                current_time,
                current_time + timedelta(seconds=self._refresh_ttl_seconds),
            )
            return await self._session_service.issue(
                user_id, session, current_time, admitted=admitted
            )

        if self._account_operations is None:
            tokens = await consume_and_create_session(admitted=False)
        else:
            async with self._account_operations.admit(user_id):
                tokens = await consume_and_create_session(admitted=True)
        return tokens, user


class SignInWithApple:
    def __init__(
        self,
        users: UserRepositoryPort,
        identities: AppleIdentityRepositoryPort,
        verifier: AppleIdentityVerifierPort,
        sessions: SessionRepositoryPort,
        session_service: SessionService,
        refresh_ttl_seconds: int,
        account_operations: AccountOperationGuard | None = None,
    ) -> None:
        self._users = users
        self._identities = identities
        self._verifier = verifier
        self._sessions = sessions
        self._session_service = session_service
        self._refresh_ttl_seconds = refresh_ttl_seconds
        self._account_operations = account_operations

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

        async def create_session(*, admitted: bool) -> AuthTokens:
            session = await self._sessions.create_or_replace(
                user_id,
                device_id,
                current_time,
                current_time + timedelta(seconds=self._refresh_ttl_seconds),
            )
            return await self._session_service.issue(
                user_id, session, current_time, admitted=admitted
            )

        if self._account_operations is None:
            tokens = await create_session(admitted=False)
        else:
            async with self._account_operations.admit(user_id):
                tokens = await create_session(admitted=True)
        return tokens, user


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
        account_merges: AccountMergeService | None = None,
        account_operations: AccountOperationGuard | None = None,
    ) -> None:
        self._users = users
        self._identities = identities
        self._link_codes = link_codes
        self._sessions = sessions
        self._session_service = session_service
        self._codes = codes
        self._review_codes = review_codes
        self._review_code_service = review_code_service
        self._account_merges = account_merges
        self._account_operations = account_operations

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

        pending_merge = None
        if self._account_merges is not None:
            pending_merge = await self._account_merges.get_by_source(current_user_id)

        if (
            pending_merge is not None
            and getattr(pending_merge, "authorized_at", None) is not None
        ):
            telegram_user_id = str(getattr(pending_merge, "target_user_id"))
            telegram_user = await self._users.get_by_id(telegram_user_id)
            if telegram_user is None:
                raise UserNotFound()
            require_telegram_username(getattr(telegram_user, "tg_username", None))
            if self._account_merges is None:
                raise RuntimeError("account merge service is required")
            await self._account_merges.continue_merge(pending_merge, current_time)
            session = await self._sessions.get_active(session_id, current_time)
            if session is None or str(getattr(session, "user_id")) != telegram_user_id:
                raise UserNotFound()
            access = self._session_service.issue_access(
                telegram_user_id, session, current_time
            )
            return access, telegram_user

        authorization_code_hash = self._codes.hash(code)
        authorization_code_kind = "link"
        candidate = await self._link_codes.find_for_link(
            authorization_code_hash, device_id, current_time
        )
        candidate_repository: LinkCodeRepositoryPort | ReviewCodeRepositoryPort = (
            self._link_codes
        )
        if (
            candidate is None
            and self._review_codes is not None
            and self._review_code_service is not None
        ):
            authorization_code_hash = self._review_code_service.hash(code)
            authorization_code_kind = "review"
            candidate = await self._review_codes.find_for_link(
                authorization_code_hash, device_id, current_time
            )
            candidate_repository = self._review_codes
        if candidate is None:
            raise InvalidLinkCode()

        telegram_user_id = str(getattr(candidate, "user_id"))
        if pending_merge is not None:
            if (
                telegram_user_id != str(getattr(pending_merge, "target_user_id"))
                or authorization_code_hash
                != str(getattr(pending_merge, "authorization_code_hash"))
                or authorization_code_kind
                != str(getattr(pending_merge, "authorization_code_kind"))
                or device_id != getattr(pending_merge, "authorization_device_id")
            ):
                raise InvalidLinkCode()
        telegram_user = await self._users.get_by_id(telegram_user_id)
        if telegram_user is None:
            raise UserNotFound()
        require_telegram_username(getattr(telegram_user, "tg_username", None))

        current_identity = await self._identities.get_by_user_id(current_user_id)
        if current_identity is None and pending_merge is None:
            raise AppleIdentityConflict()
        apple_subject = (
            str(getattr(pending_merge, "apple_subject"))
            if pending_merge is not None
            else str(getattr(current_identity, "subject"))
        )
        existing_identity = await self._identities.get_by_user_id(telegram_user_id)
        if (
            existing_identity is not None
            and str(getattr(existing_identity, "subject")) != apple_subject
        ):
            raise TelegramIdentityConflict()

        merge_journal = pending_merge
        if telegram_user_id != current_user_id and merge_journal is None:
            if self._account_merges is None:
                raise RuntimeError("account merge service is required")
            current_user = await self._users.get_by_id(current_user_id)
            if current_user is None:
                raise UserNotFound()
            merge_journal = await self._account_merges.prepare(
                current_user,
                telegram_user,
                apple_subject,
                authorization_code_hash,
                authorization_code_kind,
                device_id,
                current_time,
            )

        merge_authorized = False
        if getattr(candidate, "status") == LinkCodeStatus.ISSUED:
            if (
                telegram_user_id == current_user_id
                and self._account_operations is not None
            ):
                async with self._account_operations.admit(current_user_id):
                    consumed = await candidate_repository.consume(
                        str(getattr(candidate, "code_hash")),
                        device_id,
                        current_time,
                    )
            elif telegram_user_id != current_user_id:
                if self._account_merges is None or merge_journal is None:
                    raise RuntimeError("account merge service is required")

                async def consume_merge_proof() -> object | None:
                    return await candidate_repository.consume(
                        str(getattr(candidate, "code_hash")),
                        device_id,
                        current_time,
                    )

                (
                    merge_journal,
                    consumed,
                ) = await self._account_merges.consume_and_authorize(
                    merge_journal, consume_merge_proof, current_time
                )
                merge_authorized = consumed is not None
            else:
                consumed = await candidate_repository.consume(
                    str(getattr(candidate, "code_hash")), device_id, current_time
                )
            if consumed is None:
                raise InvalidLinkCode()

        if telegram_user_id != current_user_id:
            if self._account_merges is None or merge_journal is None:
                raise RuntimeError("account merge service is required")
            if not merge_authorized:
                merge_journal = await self._account_merges.authorize(
                    merge_journal, current_time
                )
            await self._account_merges.continue_merge(merge_journal, current_time)
            session = await self._sessions.get_active(session_id, current_time)
            if session is None or str(getattr(session, "user_id")) != telegram_user_id:
                raise UserNotFound()

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
