import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from src.domain.enums import AccountDeletionStatus
from src.domain.errors import AccountOperationConflict, UserNotFound
from src.domain.ports import AccountDeletionRepositoryPort, UserRepositoryPort
from src.services.account_operations import (
    AccountOperationGuard,
    wait_task_uninterruptibly,
)
from src.services.photos import PhotoService


logger = logging.getLogger(__name__)


class AccountDeletionService:
    def __init__(
        self,
        deletions: AccountDeletionRepositoryPort,
        users: UserRepositoryPort,
        photos: PhotoService,
        account_operations: AccountOperationGuard,
    ) -> None:
        self._deletions = deletions
        self._users = users
        self._photos = photos
        self._account_operations = account_operations

    async def delete(self, user_id: str) -> None:
        async with self._account_operations.exclusive(user_id):
            await self._account_operations.ensure_available(user_id)
            user = await self._users.get_by_id(user_id)
            if user is None:
                raise UserNotFound()
            now = datetime.now(UTC)
            # The journal becomes durable before the fence. The account lock
            # spans both writes and the destructive sweep.
            intent = self._account_operations.publish_intent(
                "deletion",
                user_id,
                [user_id],
                {"created_at": now.isoformat()},
            )
            prepare_task = asyncio.create_task(
                self._deletions.prepare(user, now, intent.journal_id)
            )
            try:
                deletion = await asyncio.shield(prepare_task)
            except asyncio.CancelledError:
                self._account_operations.poison_many([user_id])
                try:
                    await wait_task_uninterruptibly(prepare_task)
                except BaseException:
                    pass
                else:
                    self._account_operations.complete_intent(intent)
                raise
            except AccountOperationConflict:
                persisted = await asyncio.shield(self._deletions.get_by_user(user_id))
                if persisted is None:
                    # A conflicting merge/fence is already durable and keeps
                    # admission closed; this deletion wrote no journal.
                    self._account_operations.complete_intent(intent)
                raise
            except BaseException:
                self._account_operations.poison_many([user_id])
                raise
            self._account_operations.complete_intent(intent)
            deletion = await self._deletions.advance(deletion, now)
            await self._cleanup_safely(deletion, now)

    async def reconcile_startup(self) -> None:
        """Reinstall every incomplete fence before the ASGI app accepts traffic."""

        await self.reconcile_intents()
        now = datetime.now(UTC)
        for deletion in await self._deletions.list_incomplete(0):
            user_id = str(getattr(deletion, "user_id"))
            async with self._account_operations.exclusive(user_id):
                await self._ensure_fence_locked(deletion, now)

    async def process_incomplete(self, limit: int = 25) -> None:
        await self.reconcile_intents()
        now = datetime.now(UTC)
        for deletion in await self._deletions.list_incomplete(limit):
            try:
                user_id = str(getattr(deletion, "user_id"))
                async with self._account_operations.exclusive(user_id):
                    await self._ensure_fence_locked(deletion, now)
                    if getattr(deletion, "status") == AccountDeletionStatus.PREPARED:
                        deletion = await self._deletions.advance(deletion, now)
                    await self._cleanup_safely(deletion, now)
            except Exception:
                logger.exception(
                    "Account deletion reconciliation remains pending deletion_id=%s",
                    getattr(deletion, "id", "unknown"),
                )

    async def reconcile_intents(self) -> None:
        now = datetime.now(UTC)
        for intent in self._account_operations.intents_for("deletion"):
            try:
                async with self._account_operations.exclusive_many(intent.user_ids):
                    deletion = await self._deletions.get_by_user(intent.lookup_user_id)
                    if deletion is None:
                        user = await self._users.get_by_id(intent.lookup_user_id)
                        created_at = intent.payload.get("created_at")
                        if user is None or not isinstance(created_at, str):
                            raise AccountOperationConflict()
                        deletion = await self._deletions.prepare(
                            user,
                            datetime.fromisoformat(created_at),
                            intent.journal_id,
                        )
                    if [str(getattr(deletion, "user_id"))] != intent.user_ids:
                        raise AccountOperationConflict()
                    await self._ensure_fence_locked(deletion, now)
                    self._account_operations.complete_intent(intent)
            except Exception:
                logger.exception(
                    "Durable deletion intent remains pending intent_id=%s",
                    intent.intent_id,
                )

    async def _cleanup_safely(self, deletion: Any, now: datetime) -> None:
        try:
            await self._photos.delete_all(
                getattr(deletion, "telescan_id"),
                getattr(deletion, "photo_url", None),
            )
            await self._deletions.mark_cleanup_completed(
                str(getattr(deletion, "id")), now
            )
        except Exception:
            await self._deletions.record_cleanup_attempt(
                str(getattr(deletion, "id")), now
            )
            logger.exception(
                "Account deletion photo cleanup remains pending deletion_id=%s",
                getattr(deletion, "id", "unknown"),
            )

    async def _ensure_fence_locked(self, deletion: Any, now: datetime) -> None:
        user_id = str(getattr(deletion, "user_id"))
        self._account_operations.poison_many([user_id])
        await self._deletions.ensure_fence(deletion, now)
        self._account_operations.unpoison_many([user_id])
