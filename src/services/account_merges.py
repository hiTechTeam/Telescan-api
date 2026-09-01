import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.domain.enums import AccountMergeStatus
from src.domain.errors import (
    AccountOperationConflict,
    AppleIdentityConflict,
    TelegramIdentityConflict,
)
from src.domain.ports import AccountMergeRepositoryPort, UserRepositoryPort
from src.services.account_operations import (
    AccountOperationGuard,
    wait_task_uninterruptibly,
)
from src.services.photos import PhotoService


logger = logging.getLogger(__name__)


class AccountMergeService:
    def __init__(
        self,
        merges: AccountMergeRepositoryPort,
        users: UserRepositoryPort,
        photos: PhotoService,
        account_operations: AccountOperationGuard,
    ) -> None:
        self._merges = merges
        self._users = users
        self._photos = photos
        self._account_operations = account_operations

    async def get_by_source(self, source_user_id: str) -> Any | None:
        return await self._merges.get_by_source(source_user_id)

    async def merge(
        self,
        source_user: Any,
        target_user: Any,
        apple_subject: str,
        code_hash: str,
        code_kind: str,
        device_id: UUID,
        now: datetime,
    ) -> Any:
        journal = await self.prepare(
            source_user,
            target_user,
            apple_subject,
            code_hash,
            code_kind,
            device_id,
            now,
        )
        journal = await self.authorize(journal, now)
        return await self.continue_merge(journal, now)

    async def prepare(
        self,
        source_user: Any,
        target_user: Any,
        apple_subject: str,
        code_hash: str,
        code_kind: str,
        device_id: UUID,
        now: datetime,
    ) -> Any:
        source_id = str(getattr(source_user, "id"))
        target_id = str(getattr(target_user, "id"))
        user_ids = [source_id, target_id]
        async with self._account_operations.exclusive_many(user_ids):
            await self._account_operations.ensure_many_available(user_ids)
            fresh_source = await self._users.get_by_id(source_id)
            fresh_target = await self._users.get_by_id(target_id)
            if fresh_source is None or fresh_target is None:
                raise AccountOperationConflict()
            intent = self._account_operations.publish_intent(
                "merge",
                source_id,
                user_ids,
                {
                    "target_user_id": target_id,
                    "apple_subject": apple_subject,
                    "code_hash": code_hash,
                    "code_kind": code_kind,
                    "device_id": str(device_id),
                    "created_at": now.isoformat(),
                },
            )
            # The PREPARED journal is written before its durable fences. The
            # locks remain held until both fences are installed, so no live
            # writer can cross that crash-recoverable boundary.
            prepare_task = asyncio.create_task(
                self._merges.prepare(
                    fresh_source,
                    fresh_target,
                    apple_subject,
                    code_hash,
                    code_kind,
                    device_id,
                    now,
                    intent.journal_id,
                )
            )
            try:
                journal = await asyncio.shield(prepare_task)
            except asyncio.CancelledError:
                # Do not release the in-process locks while an acknowledged
                # Mongo operation may still materialize a journal. Subsequent
                # cancellation requests are delayed until the inner task has
                # either installed both fences or reached a known failure.
                self._account_operations.poison_many(user_ids)
                try:
                    await wait_task_uninterruptibly(prepare_task)
                except BaseException:
                    pass
                else:
                    self._account_operations.complete_intent(intent)
                raise
            except (
                AccountOperationConflict,
                AppleIdentityConflict,
                TelegramIdentityConflict,
            ):
                # Domain conflicts have a determinate outcome. Remap poison to
                # an already-durable journal, if that is what caused conflict.
                self._account_operations.poison_many(user_ids)
                persisted = await asyncio.shield(self._merges.get_by_source(source_id))
                if persisted is None:
                    self._account_operations.complete_intent(intent)
                else:
                    persisted_users = self._journal_users(persisted)
                    if set(persisted_users) != set(intent.user_ids):
                        self._account_operations.complete_intent(intent)
                    self._account_operations.poison_many(persisted_users)
                raise
            except BaseException:
                # A driver timeout/write concern error has an unknown server
                # outcome. Keep admission closed until process restart performs
                # synchronous journal/fence reconciliation.
                self._account_operations.poison_many(user_ids)
                raise
            self._account_operations.complete_intent(intent)
            return journal

    async def authorize(self, journal: Any, now: datetime) -> Any:
        async with self._account_operations.exclusive_many(
            self._journal_users(journal)
        ):
            await self._ensure_fences_locked(journal, now)
            return await self._merges.authorize(journal, now)

    async def consume_and_authorize(
        self,
        journal: Any,
        consume: Callable[[], Awaitable[Any | None]],
        now: datetime,
    ) -> tuple[Any, Any | None]:
        """Consume the proof and authorize while both saga locks stay held."""

        user_ids = self._journal_users(journal)
        async with self._account_operations.exclusive_many(user_ids):
            await self._ensure_fences_locked(journal, now)
            consumed = await consume()
            if consumed is None:
                return journal, None
            return await self._merges.authorize(journal, now), consumed

    async def continue_merge(self, journal: Any, now: datetime) -> Any:
        async with self._account_operations.exclusive_many(
            self._journal_users(journal)
        ):
            return await self._continue_locked(journal, now)

    async def _continue_locked(self, journal: Any, now: datetime) -> Any:
        status = getattr(journal, "status")
        if status in {AccountMergeStatus.PREPARED, AccountMergeStatus.MIGRATING}:
            await self._ensure_fences_locked(journal, now)
        if status == AccountMergeStatus.PREPARED:
            if getattr(journal, "authorized_at", None) is None:
                raise RuntimeError("merge journal is not authorized")
            journal = await self._merges.migrate(journal, now)
        elif status == AccountMergeStatus.MIGRATING:
            journal = await self._merges.migrate(journal, now)
        elif status == AccountMergeStatus.COMPLETED:
            return journal
        elif status != AccountMergeStatus.MONGO_COMPLETE:
            raise RuntimeError(f"merge journal has invalid status: {status}")
        await self._cleanup_safely(journal, now)
        return journal

    async def resume(self, source_user_id: str, now: datetime) -> Any:
        journal = await self._merges.get_by_source(source_user_id)
        if journal is None:
            raise LookupError(source_user_id)
        async with self._account_operations.exclusive_many(
            self._journal_users(journal)
        ):
            current = await self._merges.get_by_source(source_user_id)
            if current is None:
                raise LookupError(source_user_id)
            await self._ensure_fences_locked(current, now)
            if getattr(current, "status") == AccountMergeStatus.PREPARED:
                if not await self._reconcile_authorization_locked(current, now):
                    return current
                refreshed = await self._merges.get_by_source(source_user_id)
                if refreshed is None:
                    raise LookupError(source_user_id)
                current = refreshed
            return await self._continue_locked(current, now)

    async def reconcile_startup(self) -> None:
        """Reinstall every incomplete fence before the ASGI app accepts traffic."""

        await self.reconcile_intents()
        now = datetime.now(UTC)
        for journal in await self._merges.list_incomplete(0):
            async with self._account_operations.exclusive_many(
                self._journal_users(journal)
            ):
                await self._ensure_fences_locked(journal, now)

    async def process_incomplete(self, limit: int = 25) -> None:
        await self.reconcile_intents()
        now = datetime.now(UTC)
        for listed in await self._merges.list_incomplete(limit):
            try:
                async with self._account_operations.exclusive_many(
                    self._journal_users(listed)
                ):
                    journal = await self._merges.get_by_source(
                        str(getattr(listed, "source_user_id"))
                    )
                    if journal is None:
                        continue
                    await self._ensure_fences_locked(journal, now)
                    status = getattr(journal, "status")
                    if status == AccountMergeStatus.PREPARED:
                        if not await self._reconcile_authorization_locked(journal, now):
                            continue
                        journal = await self._merges.get_by_source(
                            str(getattr(journal, "source_user_id"))
                        )
                        if journal is None:
                            continue
                    await self._continue_locked(journal, now)
            except Exception:
                logger.exception(
                    "Account merge reconciliation remains pending merge_id=%s",
                    getattr(listed, "id", "unknown"),
                )

    async def reconcile_intents(self) -> None:
        now = datetime.now(UTC)
        for intent in self._account_operations.intents_for("merge"):
            try:
                async with self._account_operations.exclusive_many(intent.user_ids):
                    journal = await self._merges.get_by_source(intent.lookup_user_id)
                    if journal is None:
                        source = await self._users.get_by_id(intent.lookup_user_id)
                        target_user_id = intent.payload["target_user_id"]
                        if not isinstance(target_user_id, str):
                            raise RuntimeError("merge intent target is invalid")
                        target = await self._users.get_by_id(target_user_id)
                        if source is None or target is None:
                            raise AccountOperationConflict()
                        journal = await self._merges.prepare(
                            source,
                            target,
                            self._required_payload(intent, "apple_subject"),
                            self._required_payload(intent, "code_hash"),
                            self._required_payload(intent, "code_kind"),
                            UUID(self._required_payload(intent, "device_id")),
                            datetime.fromisoformat(
                                self._required_payload(intent, "created_at")
                            ),
                            intent.journal_id,
                        )
                    if set(self._journal_users(journal)) != set(intent.user_ids):
                        raise AccountOperationConflict()
                    await self._ensure_fences_locked(journal, now)
                    self._account_operations.complete_intent(intent)
            except Exception:
                logger.exception(
                    "Durable merge intent remains pending intent_id=%s",
                    intent.intent_id,
                )

    async def _cleanup_safely(self, journal: Any, now: datetime) -> None:
        try:
            # Source and target locks are still held. The source fence remains
            # durable through S3 cleanup; the canonical target fence is opened
            # only after all Mongo references to the source are gone.
            await self._users.delete(str(getattr(journal, "source_user_id")))
            await self._merges.release_target_fence(
                str(getattr(journal, "id")),
                str(getattr(journal, "target_user_id")),
            )
            await self._photos.delete_all(
                getattr(journal, "source_telescan_id"),
                getattr(journal, "source_photo_url", None),
            )
            await self._merges.mark_cleanup_completed(str(getattr(journal, "id")), now)
        except Exception:
            await self._merges.record_cleanup_attempt(str(getattr(journal, "id")), now)
            logger.exception(
                "Account merge cleanup remains pending merge_id=%s",
                getattr(journal, "id", "unknown"),
            )

    @staticmethod
    def _journal_users(journal: Any) -> list[str]:
        return [
            str(getattr(journal, "source_user_id")),
            str(getattr(journal, "target_user_id")),
        ]

    @staticmethod
    def _required_payload(intent: Any, field: str) -> str:
        value = intent.payload.get(field)
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"merge intent {field} is invalid")
        return value

    async def _ensure_fences_locked(self, journal: Any, now: datetime) -> None:
        user_ids = self._journal_users(journal)
        # If either Mongo write fails or this task is cancelled, admission
        # remains locally poisoned until a complete durable reaffirmation.
        self._account_operations.poison_many(user_ids)
        await self._merges.ensure_fences(journal, now)
        self._account_operations.unpoison_many(user_ids)

    async def _reconcile_authorization_locked(
        self, journal: Any, now: datetime
    ) -> bool:
        user_ids = self._journal_users(journal)
        self._account_operations.poison_many(user_ids)
        reconciled = await self._merges.reconcile_authorization(journal, now)
        self._account_operations.unpoison_many(user_ids)
        return reconciled
