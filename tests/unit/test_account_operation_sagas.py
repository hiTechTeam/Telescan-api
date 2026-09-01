import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4
import pytest
from beanie import PydanticObjectId

from src.domain.enums import AccountDeletionStatus, AccountMergeStatus
from src.domain.errors import AccountOperationConflict, TelegramIdentityConflict
from src.services.account_deletions import AccountDeletionService
from src.services.account_merges import AccountMergeService
from src.services.account_operations import AccountOperationGuard
from src.services.account_operation_intents import FileAccountOperationIntentStore
from src.services.photos import PhotoService
from src.repositories.account_merges import AccountMergeRepository
from tests.fakes import FakeStorage, FakeUsers


class FailingOncePrefixStorage(FakeStorage):
    def __init__(self) -> None:
        super().__init__()
        self.fail_prefix_once = True

    async def delete_user_prefix(self, telescan_id):
        if self.fail_prefix_once:
            self.fail_prefix_once = False
            raise OSError("storage unavailable")
        await super().delete_user_prefix(telescan_id)


class MemoryFences:
    def __init__(self) -> None:
        self.fenced: dict[str, tuple[str, str]] = {}

    async def install(self, user_id, operation_kind, operation_id, now):
        owner = self.fenced.get(user_id)
        requested = (operation_kind, operation_id)
        if owner is not None and owner != requested:
            raise RuntimeError("fence conflict")
        self.fenced[user_id] = requested

    async def release_operation(self, user_id, operation_kind, operation_id):
        if self.fenced.get(user_id) == (operation_kind, operation_id):
            self.fenced.pop(user_id)

    async def mark_completed(
        self, user_id, operation_kind, operation_id, retention_until, now
    ):
        return None

    async def is_fenced(self, user_id):
        return user_id in self.fenced


class FailSecondReaffirmFences(MemoryFences):
    def __init__(self) -> None:
        super().__init__()
        self.fail_user_id: str | None = None
        self.release_calls: list[str] = []

    async def install(self, user_id, operation_kind, operation_id, now):
        if user_id == self.fail_user_id:
            raise OSError("second reaffirm unavailable")
        await super().install(user_id, operation_kind, operation_id, now)

    async def release_operation(self, user_id, operation_kind, operation_id):
        self.release_calls.append(user_id)
        await super().release_operation(user_id, operation_kind, operation_id)


class PersistThenFailMergeRepository:
    def __init__(self, fences, *, failure, existing=None) -> None:
        self.fences = fences
        self.failure = failure
        self.journal = existing

    async def get_by_source(self, source_user_id):
        if self.journal is None or str(self.journal.source_user_id) != source_user_id:
            return None
        return self.journal

    async def prepare(
        self,
        source_user,
        target_user,
        apple_subject,
        code_hash,
        code_kind,
        device_id,
        now,
        journal_id=None,
    ):
        if self.journal is None:
            self.journal = SimpleNamespace(
                id=journal_id or str(uuid4()).replace("-", "")[:24],
                source_user_id=str(source_user.id),
                target_user_id=str(target_user.id),
                source_telescan_id=source_user.telescan_id,
                source_photo_url=None,
                authorized_at=None,
                status=AccountMergeStatus.PREPARED,
            )
        raise self.failure

    async def ensure_fences(self, journal, now):
        for user_id in sorted(
            {str(journal.source_user_id), str(journal.target_user_id)}
        ):
            await self.fences.install(user_id, "merge", str(journal.id), now)

    async def list_incomplete(self, limit):
        return [self.journal] if self.journal is not None else []


class LateMaterializingMergeRepository(PersistThenFailMergeRepository):
    def __init__(self, fences) -> None:
        super().__init__(fences, failure=TimeoutError("write outcome unknown"))
        self.release_materialization = asyncio.Event()
        self.materialized = asyncio.Event()
        self.prepare_calls = 0

    async def prepare(
        self,
        source_user,
        target_user,
        apple_subject,
        code_hash,
        code_kind,
        device_id,
        now,
        journal_id=None,
    ):
        self.prepare_calls += 1
        pending = SimpleNamespace(
            id=journal_id or str(uuid4()).replace("-", "")[:24],
            source_user_id=str(source_user.id),
            target_user_id=str(target_user.id),
            source_telescan_id=source_user.telescan_id,
            source_photo_url=None,
            authorized_at=None,
            status=AccountMergeStatus.PREPARED,
        )

        async def materialize_later() -> None:
            await self.release_materialization.wait()
            self.journal = pending
            self.materialized.set()

        asyncio.create_task(materialize_later())
        raise self.failure


class RecoverableMergeRepository:
    def __init__(self, fences) -> None:
        self.fences = fences
        self.journal = None

    async def get_by_source(self, source_user_id):
        if self.journal is None or str(self.journal.source_user_id) != source_user_id:
            return None
        return self.journal

    async def prepare(
        self,
        source_user,
        target_user,
        apple_subject,
        code_hash,
        code_kind,
        device_id,
        now,
        journal_id=None,
    ):
        self.journal = SimpleNamespace(
            id=journal_id or str(uuid4()).replace("-", "")[:24],
            source_user_id=str(source_user.id),
            target_user_id=str(target_user.id),
            source_telescan_id=source_user.telescan_id,
            source_photo_url=None,
            authorized_at=None,
            status=AccountMergeStatus.PREPARED,
        )
        await self.ensure_fences(self.journal, now)
        return self.journal

    async def ensure_fences(self, journal, now):
        for user_id in sorted(
            {str(journal.source_user_id), str(journal.target_user_id)}
        ):
            await self.fences.install(user_id, "merge", str(journal.id), now)

    async def list_incomplete(self, limit):
        return [self.journal] if self.journal is not None else []


class FakeMergeJournalRepository:
    def __init__(self, journal, *, authorization_consumed=True) -> None:
        self.journal = journal
        self.authorization_consumed = authorization_consumed
        self.fail_migration_once = False
        self.cleanup_attempts = 0
        self.migrations = 0

    async def get_by_source(self, source_user_id):
        if str(self.journal.source_user_id) != source_user_id:
            return None
        if self.journal.status == AccountMergeStatus.CANCELLED:
            return None
        return self.journal

    async def prepare(
        self,
        source_user,
        target_user,
        apple_subject,
        code_hash,
        code_kind,
        device_id,
        now,
        journal_id=None,
    ):
        return self.journal

    async def authorize(self, merge, now):
        merge.authorized_at = now
        return merge

    async def ensure_fences(self, merge, now):
        return None

    async def reconcile_authorization(self, merge, now):
        if not self.authorization_consumed:
            return False
        merge.authorized_at = now
        return True

    async def migrate(self, merge, now):
        self.migrations += 1
        if merge.authorized_at is None:
            raise RuntimeError("unauthorized")
        merge.status = AccountMergeStatus.MIGRATING
        if self.fail_migration_once:
            self.fail_migration_once = False
            raise OSError("interrupted migration")
        merge.status = AccountMergeStatus.MONGO_COMPLETE
        return merge

    async def list_incomplete(self, limit):
        if self.journal.status in {
            AccountMergeStatus.PREPARED,
            AccountMergeStatus.MIGRATING,
            AccountMergeStatus.MONGO_COMPLETE,
        }:
            return [self.journal]
        return []

    async def list_cleanup_pending(self, limit):
        return await self.list_incomplete(limit)

    async def mark_cleanup_completed(self, merge_id, now):
        self.journal.status = AccountMergeStatus.COMPLETED

    async def release_target_fence(self, merge_id, target_user_id):
        return None

    async def record_cleanup_attempt(self, merge_id, now):
        self.cleanup_attempts += 1


class ActualEnsureMergeRepository(FakeMergeJournalRepository):
    def __init__(self, journal, fences) -> None:
        super().__init__(journal)
        self.actual = AccountMergeRepository(fences)

    async def ensure_fences(self, merge, now):
        await self.actual.ensure_fences(merge, now)


class FakeDeletionJournalRepository:
    def __init__(self, journal, users) -> None:
        self.journal = journal
        self.users = users
        self.fail_advance_once = True
        self.steps = []
        self.cleanup_attempts = 0

    async def prepare(self, user, now, journal_id=None):
        return self.journal

    async def get_by_user(self, user_id):
        return self.journal if str(self.journal.user_id) == user_id else None

    async def ensure_fence(self, deletion, now):
        return None

    async def advance(self, deletion, now):
        self.steps.append("sessions_revoked")
        if self.fail_advance_once:
            self.fail_advance_once = False
            raise OSError("interrupted after session revocation")
        self.steps.extend(["relations_deleted", "identity_deleted", "user_deleted"])
        await self.users.delete(str(deletion.user_id))
        deletion.status = AccountDeletionStatus.DB_COMPLETE
        return deletion

    async def list_incomplete(self, limit):
        if self.journal.status in {
            AccountDeletionStatus.PREPARED,
            AccountDeletionStatus.DB_COMPLETE,
        }:
            return [self.journal]
        return []

    async def mark_cleanup_completed(self, deletion_id, now):
        self.journal.status = AccountDeletionStatus.COMPLETED

    async def record_cleanup_attempt(self, deletion_id, now):
        self.cleanup_attempts += 1


class CrossOperationState:
    def __init__(self) -> None:
        self.merge_journal = None
        self.deletion_journal = None
        self.merge_persisted = asyncio.Event()
        self.release_merge = asyncio.Event()


class BlockingCrossMergeRepository:
    def __init__(self, state, fences) -> None:
        self.state = state
        self.fences = fences
        self.prepare_calls = 0

    async def get_by_source(self, source_user_id):
        journal = self.state.merge_journal
        if journal is None or str(journal.source_user_id) != source_user_id:
            return None
        return journal

    async def prepare(
        self,
        source_user,
        target_user,
        apple_subject,
        code_hash,
        code_kind,
        device_id,
        now,
        journal_id=None,
    ):
        self.prepare_calls += 1
        if self.state.deletion_journal is not None:
            raise AccountOperationConflict()
        journal = SimpleNamespace(
            id=journal_id or str(uuid4()).replace("-", "")[:24],
            source_user_id=str(source_user.id),
            target_user_id=str(target_user.id),
            source_telescan_id=source_user.telescan_id,
            source_photo_url=None,
            authorized_at=None,
            status=AccountMergeStatus.PREPARED,
        )
        self.state.merge_journal = journal
        self.state.merge_persisted.set()
        await self.state.release_merge.wait()
        await self.ensure_fences(journal, now)
        return journal

    async def ensure_fences(self, journal, now):
        for user_id in sorted(
            {str(journal.source_user_id), str(journal.target_user_id)}
        ):
            await self.fences.install(user_id, "merge", str(journal.id), now)


class CrossDeletionRepository:
    def __init__(self, state) -> None:
        self.state = state
        self.prepare_calls = 0

    async def prepare(self, user, now, journal_id=None):
        self.prepare_calls += 1
        if self.state.merge_journal is not None:
            raise AccountOperationConflict()
        self.state.deletion_journal = SimpleNamespace(
            id=journal_id or str(uuid4()).replace("-", "")[:24],
            user_id=str(user.id),
            telescan_id=user.telescan_id,
            photo_url=None,
            status=AccountDeletionStatus.PREPARED,
        )
        return self.state.deletion_journal

    async def get_by_user(self, user_id):
        journal = self.state.deletion_journal
        if journal is None or str(journal.user_id) != user_id:
            return None
        return journal


@pytest.mark.asyncio
async def test_merge_reconciles_interruption_and_retries_s3_outbox() -> None:
    users = FakeUsers()
    source = await users.create_unlinked()
    now = datetime.now(UTC)
    journal = SimpleNamespace(
        id="merge-1",
        source_user_id=str(source.id),
        target_user_id="target-user",
        source_telescan_id=source.telescan_id,
        source_photo_url="https://storage.example/users/source/live.jpg",
        authorized_at=now,
        status=AccountMergeStatus.PREPARED,
    )
    repository = FakeMergeJournalRepository(journal)
    repository.fail_migration_once = True
    storage = FailingOncePrefixStorage()
    service = AccountMergeService(
        repository,
        users,
        PhotoService(storage, 1024),
        AccountOperationGuard(MemoryFences()),
    )

    with pytest.raises(OSError, match="interrupted migration"):
        await service.continue_merge(journal, now)
    assert journal.status == AccountMergeStatus.MIGRATING

    await service.process_incomplete()
    assert journal.status == AccountMergeStatus.MONGO_COMPLETE
    assert repository.cleanup_attempts == 1
    assert await users.get_by_id(str(source.id)) is None

    await service.process_incomplete()
    assert journal.status == AccountMergeStatus.COMPLETED
    assert await users.get_by_id(str(source.id)) is None
    assert f"users/{source.telescan_id}/" in storage.deleted
    migrations = repository.migrations

    await service.continue_merge(journal, datetime.now(UTC))

    assert repository.migrations == migrations


@pytest.mark.asyncio
async def test_prepared_merge_requires_durable_consumption_proof() -> None:
    users = FakeUsers()
    source = await users.create_unlinked()
    journal = SimpleNamespace(
        id="merge-1",
        source_user_id=str(source.id),
        target_user_id="target-user",
        source_telescan_id=source.telescan_id,
        source_photo_url=None,
        authorized_at=None,
        status=AccountMergeStatus.PREPARED,
    )
    repository = FakeMergeJournalRepository(journal, authorization_consumed=False)
    service = AccountMergeService(
        repository,
        users,
        PhotoService(FakeStorage(), 1024),
        AccountOperationGuard(MemoryFences()),
    )

    await service.process_incomplete()
    assert repository.migrations == 0
    assert await users.get_by_id(str(source.id)) is source

    repository.authorization_consumed = True
    await service.process_incomplete()
    assert repository.migrations == 1
    assert journal.status == AccountMergeStatus.COMPLETED


@pytest.mark.asyncio
async def test_deletion_resumes_after_sessions_first_and_retries_s3() -> None:
    users = FakeUsers()
    user = await users.create_unlinked()
    user.photo_s3_link = "https://storage.example/users/user/live.jpg"
    journal = SimpleNamespace(
        id="deletion-1",
        user_id=str(user.id),
        telescan_id=user.telescan_id,
        photo_url=user.photo_s3_link,
        status=AccountDeletionStatus.PREPARED,
    )
    repository = FakeDeletionJournalRepository(journal, users)
    storage = FailingOncePrefixStorage()
    service = AccountDeletionService(
        repository,
        users,
        PhotoService(storage, 1024),
        AccountOperationGuard(MemoryFences()),
    )

    with pytest.raises(OSError, match="interrupted after session revocation"):
        await service.delete(str(user.id))
    assert repository.steps == ["sessions_revoked"]
    assert await users.get_by_id(str(user.id)) is user

    await service.process_incomplete()
    assert repository.steps[:2] == ["sessions_revoked", "sessions_revoked"]
    assert repository.steps.index("sessions_revoked") < repository.steps.index(
        "relations_deleted"
    )
    assert journal.status == AccountDeletionStatus.DB_COMPLETE
    assert repository.cleanup_attempts == 1

    await service.process_incomplete()
    assert journal.status == AccountDeletionStatus.COMPLETED
    assert await users.get_by_id(str(user.id)) is None
    assert f"users/{user.telescan_id}/" in storage.deleted


@pytest.mark.asyncio
async def test_account_lock_drains_writer_before_saga_installs_fence() -> None:
    fences = MemoryFences()
    guard = AccountOperationGuard(fences)
    user_id = "writer-user"
    writer_entered = asyncio.Event()
    release_writer = asyncio.Event()
    events: list[str] = []

    async def writer() -> None:
        async with guard.admit(user_id):
            writer_entered.set()
            await release_writer.wait()
            events.append("write")

    async def saga() -> None:
        async with guard.exclusive(user_id):
            events.append("journal")
            await fences.install(user_id, "deletion", "operation", datetime.now(UTC))
            events.append("fence")

    writer_task = asyncio.create_task(writer())
    await writer_entered.wait()
    saga_task = asyncio.create_task(saga())
    await asyncio.sleep(0)
    assert events == []

    release_writer.set()
    await asyncio.gather(writer_task, saga_task)

    assert events == ["write", "journal", "fence"]
    with pytest.raises(AccountOperationConflict):
        async with guard.admit(user_id):
            pass


@pytest.mark.asyncio
async def test_persisted_journal_failure_poison_is_reconciled_before_admission() -> (
    None
):
    users = FakeUsers()
    source = await users.create_unlinked()
    target = await users.upsert_telegram_profile(42, "Target", "target")
    fences = MemoryFences()
    guard = AccountOperationGuard(fences)
    repository = PersistThenFailMergeRepository(
        fences, failure=OSError("second fence unavailable")
    )
    service = AccountMergeService(
        repository, users, PhotoService(FakeStorage(), 1024), guard
    )

    with pytest.raises(OSError, match="second fence"):
        await service.prepare(
            source,
            target,
            "apple-subject",
            "proof",
            "link",
            uuid4(),
            datetime.now(UTC),
        )

    for user_id in (str(source.id), str(target.id)):
        with pytest.raises(AccountOperationConflict):
            async with guard.admit(user_id):
                pass

    await service.reconcile_startup()
    assert await guard.is_fenced(str(source.id)) is True
    assert await guard.is_fenced(str(target.id)) is True


@pytest.mark.asyncio
async def test_conflicting_target_does_not_leave_unrelated_target_poisoned() -> None:
    users = FakeUsers()
    source = await users.create_unlinked()
    target_a = await users.upsert_telegram_profile(42, "A", "target_a")
    target_b = await users.upsert_telegram_profile(43, "B", "target_b")
    journal = SimpleNamespace(
        id=str(uuid4()).replace("-", "")[:24],
        source_user_id=str(source.id),
        target_user_id=str(target_a.id),
        source_telescan_id=source.telescan_id,
        source_photo_url=None,
        authorized_at=None,
        status=AccountMergeStatus.PREPARED,
    )
    fences = MemoryFences()
    guard = AccountOperationGuard(fences)
    repository = PersistThenFailMergeRepository(
        fences, failure=TelegramIdentityConflict(), existing=journal
    )
    service = AccountMergeService(
        repository, users, PhotoService(FakeStorage(), 1024), guard
    )

    with pytest.raises(TelegramIdentityConflict):
        await service.prepare(
            source,
            target_b,
            "apple-subject",
            "proof",
            "link",
            uuid4(),
            datetime.now(UTC),
        )

    async with guard.admit(str(target_b.id)):
        pass
    for user_id in (str(source.id), str(target_a.id)):
        with pytest.raises(AccountOperationConflict):
            async with guard.admit(user_id):
                pass


@pytest.mark.asyncio
async def test_cancellation_after_journal_persist_keeps_local_admission_closed() -> (
    None
):
    users = FakeUsers()
    source = await users.create_unlinked()
    target = await users.upsert_telegram_profile(42, "Target", "target")
    fences = MemoryFences()
    guard = AccountOperationGuard(fences)
    repository = PersistThenFailMergeRepository(
        fences, failure=asyncio.CancelledError()
    )
    service = AccountMergeService(
        repository, users, PhotoService(FakeStorage(), 1024), guard
    )

    with pytest.raises(asyncio.CancelledError):
        await service.prepare(
            source,
            target,
            "apple-subject",
            "proof",
            "link",
            uuid4(),
            datetime.now(UTC),
        )

    with pytest.raises(AccountOperationConflict):
        async with guard.admit(str(source.id)):
            pass


@pytest.mark.asyncio
async def test_runtime_reaffirm_failure_never_opens_first_fence_and_poisons_both() -> (
    None
):
    users = FakeUsers()
    source = await users.create_unlinked()
    target = await users.upsert_telegram_profile(42, "Target", "target")
    operation_id = str(uuid4()).replace("-", "")[:24]
    journal = SimpleNamespace(
        id=operation_id,
        source_user_id=str(source.id),
        target_user_id=str(target.id),
        source_telescan_id=source.telescan_id,
        source_photo_url=None,
        authorized_at=None,
        status=AccountMergeStatus.PREPARED,
    )
    fences = FailSecondReaffirmFences()
    now = datetime.now(UTC)
    ordered = sorted([str(source.id), str(target.id)])
    for user_id in ordered:
        await fences.install(user_id, "merge", operation_id, now)
    fences.fail_user_id = ordered[1]
    guard = AccountOperationGuard(fences)
    repository = ActualEnsureMergeRepository(journal, fences)
    service = AccountMergeService(
        repository, users, PhotoService(FakeStorage(), 1024), guard
    )

    with pytest.raises(OSError, match="second reaffirm"):
        await service.authorize(journal, now)

    assert fences.release_calls == []
    assert set(fences.fenced) == set(ordered)
    # Prove the local poison remains fail-closed even if the backing fence read
    # is temporarily unavailable/missing after the failed reaffirmation.
    fences.fenced.clear()
    for user_id in ordered:
        with pytest.raises(AccountOperationConflict):
            async with guard.admit(user_id):
                pass


@pytest.mark.asyncio
async def test_concurrent_merge_and_deletion_prepare_create_only_one_journal() -> None:
    users = FakeUsers()
    source = await users.create_unlinked()
    target = await users.upsert_telegram_profile(42, "Target", "target")
    state = CrossOperationState()
    fences = MemoryFences()
    guard = AccountOperationGuard(fences)
    merge_repository = BlockingCrossMergeRepository(state, fences)
    deletion_repository = CrossDeletionRepository(state)
    merge_service = AccountMergeService(
        merge_repository,
        users,
        PhotoService(FakeStorage(), 1024),
        guard,
    )
    deletion_service = AccountDeletionService(
        deletion_repository,
        users,
        PhotoService(FakeStorage(), 1024),
        guard,
    )

    merge_task = asyncio.create_task(
        merge_service.prepare(
            source,
            target,
            "apple-subject",
            "proof",
            "link",
            uuid4(),
            datetime.now(UTC),
        )
    )
    await state.merge_persisted.wait()
    deletion_task = asyncio.create_task(deletion_service.delete(str(source.id)))
    await asyncio.sleep(0)

    # The deletion cannot pass the same per-user lock while the merge is in
    # its journal-before-fence crash boundary.
    assert deletion_repository.prepare_calls == 0
    state.release_merge.set()
    await merge_task
    with pytest.raises(AccountOperationConflict):
        await deletion_task

    assert state.merge_journal is not None
    assert state.deletion_journal is None
    assert deletion_repository.prepare_calls == 0
    assert await guard.is_fenced(str(source.id)) is True
    assert await guard.is_fenced(str(target.id)) is True


@pytest.mark.asyncio
async def test_unknown_prepare_outcome_stays_poisoned_if_journal_appears_late() -> None:
    users = FakeUsers()
    source = await users.create_unlinked()
    target = await users.upsert_telegram_profile(42, "Target", "target")
    fences = MemoryFences()
    guard = AccountOperationGuard(fences)
    repository = LateMaterializingMergeRepository(fences)
    service = AccountMergeService(
        repository,
        users,
        PhotoService(FakeStorage(), 1024),
        guard,
    )

    with pytest.raises(TimeoutError, match="outcome unknown"):
        await service.prepare(
            source,
            target,
            "apple-subject",
            "proof",
            "link",
            uuid4(),
            datetime.now(UTC),
        )
    assert await repository.get_by_source(str(source.id)) is None

    repository.release_materialization.set()
    await repository.materialized.wait()
    assert await repository.get_by_source(str(source.id)) is not None
    for user_id in (str(source.id), str(target.id)):
        with pytest.raises(AccountOperationConflict):
            async with guard.admit(user_id):
                pass
    with pytest.raises(AccountOperationConflict):
        await service.prepare(
            source,
            target,
            "apple-subject",
            "proof",
            "link",
            uuid4(),
            datetime.now(UTC),
        )
    assert repository.prepare_calls == 1


@pytest.mark.asyncio
async def test_client_cancellation_waits_for_journal_and_fences_before_unlock() -> None:
    users = FakeUsers()
    source = await users.create_unlinked()
    target = await users.upsert_telegram_profile(42, "Target", "target")
    state = CrossOperationState()
    fences = MemoryFences()
    guard = AccountOperationGuard(fences)
    repository = BlockingCrossMergeRepository(state, fences)
    service = AccountMergeService(
        repository,
        users,
        PhotoService(FakeStorage(), 1024),
        guard,
    )
    merge_task = asyncio.create_task(
        service.prepare(
            source,
            target,
            "apple-subject",
            "proof",
            "link",
            uuid4(),
            datetime.now(UTC),
        )
    )
    await state.merge_persisted.wait()
    merge_task.cancel()

    async def late_writer() -> None:
        async with guard.admit(str(source.id)):
            raise AssertionError("writer crossed the journal/fence boundary")

    writer_task = asyncio.create_task(late_writer())
    await asyncio.sleep(0)
    assert writer_task.done() is False

    state.release_merge.set()
    with pytest.raises(asyncio.CancelledError):
        await merge_task
    with pytest.raises(AccountOperationConflict):
        await writer_task


@pytest.mark.asyncio
async def test_durable_intent_blocks_restart_until_late_journal_is_fenced(
    tmp_path,
) -> None:
    source = SimpleNamespace(id=PydanticObjectId(), telescan_id=uuid4())
    target = SimpleNamespace(id=PydanticObjectId(), telescan_id=uuid4())

    class ObjectIdUsers:
        async def get_by_id(self, user_id):
            for user in (source, target):
                if str(user.id) == user_id:
                    return user
            return None

    intent_parent = tmp_path / "runtime"
    intent_parent.mkdir()
    intent_directory = intent_parent / "operation-intents"
    fences = MemoryFences()
    repository = LateMaterializingMergeRepository(fences)
    first_guard = AccountOperationGuard(
        fences,
        FileAccountOperationIntentStore(intent_directory),
    )
    first_service = AccountMergeService(
        repository,
        ObjectIdUsers(),
        PhotoService(FakeStorage(), 1024),
        first_guard,
    )

    with pytest.raises(TimeoutError, match="outcome unknown"):
        await first_service.prepare(
            source,
            target,
            "apple-subject",
            "proof",
            "link",
            uuid4(),
            datetime.now(UTC),
        )
    intent_files = list(intent_directory.glob("*.json"))
    assert len(intent_files) == 1
    assert intent_files[0].stat().st_mode & 0o777 == 0o600

    # A fresh process restores the fsynced host intent before its first Mongo
    # scan. The journal is still absent, so both accounts remain unavailable.
    restarted_guard = AccountOperationGuard(
        fences,
        FileAccountOperationIntentStore(intent_directory),
    )
    restarted_guard.restore_durable_intents()
    restarted_service = AccountMergeService(
        repository,
        ObjectIdUsers(),
        PhotoService(FakeStorage(), 1024),
        restarted_guard,
    )
    await restarted_service.reconcile_startup()
    for user_id in (str(source.id), str(target.id)):
        with pytest.raises(AccountOperationConflict):
            async with restarted_guard.admit(user_id):
                pass

    repository.release_materialization.set()
    await repository.materialized.wait()
    await restarted_service.reconcile_startup()

    assert list(intent_directory.glob("*.json")) == []
    assert await restarted_guard.is_fenced(str(source.id)) is True
    assert await restarted_guard.is_fenced(str(target.id)) is True


@pytest.mark.asyncio
async def test_restart_materializes_journal_after_crash_between_intent_and_insert(
    tmp_path,
) -> None:
    source = SimpleNamespace(id=PydanticObjectId(), telescan_id=uuid4())
    target = SimpleNamespace(id=PydanticObjectId(), telescan_id=uuid4())

    class ObjectIdUsers:
        async def get_by_id(self, user_id):
            for user in (source, target):
                if str(user.id) == user_id:
                    return user
            return None

    intent_parent = tmp_path / "runtime"
    intent_parent.mkdir()
    intent_directory = intent_parent / "operation-intents"
    store = FileAccountOperationIntentStore(intent_directory)
    first_guard = AccountOperationGuard(MemoryFences(), store)
    now = datetime.now(UTC)
    device_id = uuid4()
    intent = first_guard.publish_intent(
        "merge",
        str(source.id),
        [str(source.id), str(target.id)],
        {
            "target_user_id": str(target.id),
            "apple_subject": "apple-subject",
            "code_hash": "proof-hash",
            "code_kind": "link",
            "device_id": str(device_id),
            "created_at": now.isoformat(),
        },
    )

    # Simulate SIGKILL before the Mongo prepare call. A fresh process restores
    # the fsynced payload and deterministically materializes the same journal.
    fences = MemoryFences()
    restarted_guard = AccountOperationGuard(fences, store)
    restarted_guard.restore_durable_intents()
    repository = RecoverableMergeRepository(fences)
    service = AccountMergeService(
        repository,
        ObjectIdUsers(),
        PhotoService(FakeStorage(), 1024),
        restarted_guard,
    )

    await service.reconcile_startup()

    assert repository.journal is not None
    assert str(repository.journal.id) == intent.journal_id
    assert list(intent_directory.glob("*.json")) == []
    assert set(fences.fenced) == {str(source.id), str(target.id)}
