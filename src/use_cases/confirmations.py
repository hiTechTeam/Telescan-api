from datetime import UTC, datetime, timedelta
from uuid import UUID

from src.domain.entities import ConfirmationResult
from src.domain.enums import ConfirmationStatus
from src.domain.errors import ConfirmationNotFound, ForbiddenConfirmation, UserNotFound
from src.domain.ports import (
    BotGatewayPort,
    ConfirmationRepositoryPort,
    SessionRepositoryPort,
    UserRepositoryPort,
)
from src.services.account_operations import AccountOperationGuard


class RequestLogoutAll:
    def __init__(
        self,
        users: UserRepositoryPort,
        confirmations: ConfirmationRepositoryPort,
        bot: BotGatewayPort,
        ttl_seconds: int,
        account_operations: AccountOperationGuard | None = None,
    ) -> None:
        self._users = users
        self._confirmations = confirmations
        self._bot = bot
        self._ttl_seconds = ttl_seconds
        self._account_operations = account_operations

    async def execute(
        self, user_id: str, now: datetime | None = None
    ) -> ConfirmationResult:
        current_time = now or datetime.now(UTC)
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFound()
        if self._account_operations is None:
            request = await self._confirmations.create_logout_all(
                user_id,
                current_time,
                current_time + timedelta(seconds=self._ttl_seconds),
            )
            await self._bot.request_logout_all_confirmation(
                getattr(request, "public_id"),
                getattr(user, "tg_id"),
                getattr(request, "expires_at"),
            )
        else:
            async with self._account_operations.admit(user_id):
                request = await self._confirmations.create_logout_all(
                    user_id,
                    current_time,
                    current_time + timedelta(seconds=self._ttl_seconds),
                )
                await self._bot.request_logout_all_confirmation(
                    getattr(request, "public_id"),
                    getattr(user, "tg_id"),
                    getattr(request, "expires_at"),
                )
        return ConfirmationResult(
            status=ConfirmationStatus.PENDING,
            confirmation_id=getattr(request, "public_id"),
        )


class DecideConfirmation:
    def __init__(
        self,
        users: UserRepositoryPort,
        confirmations: ConfirmationRepositoryPort,
        sessions: SessionRepositoryPort,
        account_operations: AccountOperationGuard | None = None,
    ) -> None:
        self._users = users
        self._confirmations = confirmations
        self._sessions = sessions
        self._account_operations = account_operations

    async def execute(
        self,
        confirmation_id: UUID,
        telegram_id: int,
        decision: ConfirmationStatus,
        now: datetime | None = None,
    ) -> ConfirmationResult:
        current_time = now or datetime.now(UTC)
        user = await self._users.get_by_tg_id(telegram_id)
        if user is None:
            raise ForbiddenConfirmation()
        user_id = str(getattr(user, "id"))

        async def decide() -> object:
            if decision == ConfirmationStatus.EXPIRED:
                request = await self._confirmations.expire(
                    confirmation_id, user_id, current_time
                )
            else:
                request = await self._confirmations.decide(
                    confirmation_id, user_id, decision, current_time
                )
            if request is None:
                raise ConfirmationNotFound()
            if getattr(request, "status") == ConfirmationStatus.CONFIRMED:
                await self._sessions.revoke_all(user_id, current_time)
            return request

        if self._account_operations is None:
            request = await decide()
        else:
            async with self._account_operations.admit(user_id):
                request = await decide()
        status = getattr(request, "status")
        return ConfirmationResult(
            status=status,
            confirmation_id=confirmation_id,
            telegram_chat_id=getattr(request, "telegram_chat_id", None),
            telegram_message_id=getattr(request, "telegram_message_id", None),
        )


class GetConfirmationStatus:
    def __init__(
        self,
        confirmations: ConfirmationRepositoryPort,
        account_operations: AccountOperationGuard | None = None,
    ) -> None:
        self._confirmations = confirmations
        self._account_operations = account_operations

    async def execute(
        self,
        confirmation_id: UUID,
        user_id: str,
        now: datetime | None = None,
    ) -> ConfirmationResult:
        current_time = now or datetime.now(UTC)
        request = await self._confirmations.get_for_user(confirmation_id, user_id)
        if request is None:
            raise ConfirmationNotFound()
        if (
            getattr(request, "status") == ConfirmationStatus.PENDING
            and getattr(request, "expires_at") <= current_time
        ):
            if self._account_operations is None:
                request = await self._confirmations.expire(
                    confirmation_id, user_id, current_time
                )
            else:
                async with self._account_operations.admit(user_id):
                    request = await self._confirmations.expire(
                        confirmation_id, user_id, current_time
                    )
            if request is None:
                raise ConfirmationNotFound()
        return ConfirmationResult(
            status=getattr(request, "status"),
            confirmation_id=confirmation_id,
        )


class ListPendingConfirmations:
    def __init__(self, confirmations: ConfirmationRepositoryPort) -> None:
        self._confirmations = confirmations

    async def execute(self) -> list[object]:
        return await self._confirmations.list_pending()


class RegisterConfirmationMessage:
    def __init__(self, confirmations: ConfirmationRepositoryPort) -> None:
        self._confirmations = confirmations

    async def execute(
        self, confirmation_id: UUID, chat_id: int, message_id: int
    ) -> object:
        request = await self._confirmations.register_message(
            confirmation_id, chat_id, message_id
        )
        if request is None:
            raise ConfirmationNotFound()
        return request
