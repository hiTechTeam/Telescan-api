import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from src.domain.errors import AccountOperationConflict
from src.domain.ports import AccountOperationFenceRepositoryPort
from src.services.account_operation_intents import (
    AccountOperationIntent,
    AccountOperationIntentStore,
    InMemoryAccountOperationIntentStore,
    IntentValue,
)


async def wait_task_uninterruptibly[T](task: asyncio.Task[T]) -> T:
    """Wait for a critical task even if its caller receives more cancellations."""

    while True:
        if task.done():
            return task.result()
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                return task.result()


class AccountOperationGuard:
    """Serialize account writes inside the single active API process.

    Production deliberately runs exactly one API process. A normal mutation
    takes the per-account locks and checks the durable fence *after* acquiring
    them. A destructive saga takes the same locks without the admission check,
    persists its journal, closes the durable fence, and only then releases the
    locks. A process crash clears all live writers while the journal remains
    available for fail-closed startup reconciliation.
    """

    def __init__(
        self,
        fences: AccountOperationFenceRepositoryPort,
        intents: AccountOperationIntentStore | None = None,
    ) -> None:
        self._fences = fences
        self._intents = intents or InMemoryAccountOperationIntentStore()
        self._locks: dict[str, asyncio.Lock] = {}
        self._registry_lock = asyncio.Lock()
        self._poisoned: set[str] = set()

    async def is_fenced(self, user_id: str) -> bool:
        return user_id in self._poisoned or await self._fences.is_fenced(user_id)

    def poison_many(self, user_ids: list[str]) -> None:
        """Keep admission closed after a journal/fence write failed in-process."""

        self._poisoned.update(user_ids)

    def unpoison_many(self, user_ids: list[str]) -> None:
        for user_id in user_ids:
            self._poisoned.discard(user_id)

    def has_local_poison(self, user_ids: list[str]) -> bool:
        return any(user_id in self._poisoned for user_id in user_ids)

    def publish_intent(
        self,
        operation_kind: str,
        lookup_user_id: str,
        user_ids: list[str],
        payload: dict[str, IntentValue],
    ) -> AccountOperationIntent:
        intent = self._intents.publish(
            operation_kind,
            lookup_user_id,
            user_ids,
            payload,
        )
        self.poison_many(intent.user_ids)
        return intent

    def complete_intent(self, intent: AccountOperationIntent) -> None:
        self._intents.complete(intent.intent_id)
        self.unpoison_many(intent.user_ids)

    def restore_durable_intents(self) -> None:
        for intent in self._intents.list():
            self.poison_many(intent.user_ids)

    def intents_for(self, operation_kind: str) -> list[AccountOperationIntent]:
        return self._intents.list(operation_kind)

    async def ensure_available(self, user_id: str) -> None:
        if await self.is_fenced(user_id):
            raise AccountOperationConflict()

    async def ensure_many_available(self, user_ids: list[str]) -> None:
        for user_id in sorted(set(user_ids)):
            await self.ensure_available(user_id)

    @asynccontextmanager
    async def admit(self, user_id: str) -> AsyncIterator[None]:
        async with self.admit_many([user_id]):
            yield

    @asynccontextmanager
    async def admit_many(self, user_ids: list[str]) -> AsyncIterator[None]:
        async with self.exclusive_many(user_ids):
            for user_id in sorted(set(user_ids)):
                if user_id in self._poisoned or await self._fences.is_fenced(user_id):
                    raise AccountOperationConflict()
            yield

    @asynccontextmanager
    async def exclusive(self, user_id: str) -> AsyncIterator[None]:
        async with self.exclusive_many([user_id]):
            yield

    @asynccontextmanager
    async def exclusive_many(self, user_ids: list[str]) -> AsyncIterator[None]:
        ordered_user_ids = sorted(set(user_ids))
        locks = await self._locks_for(ordered_user_ids)
        acquired: list[asyncio.Lock] = []
        try:
            for lock in locks:
                await lock.acquire()
                acquired.append(lock)
            yield
        finally:
            for lock in reversed(acquired):
                lock.release()

    async def _locks_for(self, user_ids: list[str]) -> list[asyncio.Lock]:
        async with self._registry_lock:
            return [
                self._locks.setdefault(user_id, asyncio.Lock()) for user_id in user_ids
            ]


__all__ = ["AccountOperationGuard", "wait_task_uninterruptibly"]
