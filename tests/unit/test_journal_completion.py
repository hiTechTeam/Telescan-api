from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from beanie import PydanticObjectId

from src.domain.enums import AccountDeletionStatus, AccountMergeStatus
from src.infrastructure.mongodb.documents import (
    AccountDeletionDocument,
    AccountMergeDocument,
)
from src.repositories.account_deletions import AccountDeletionRepository
from src.repositories.account_merges import AccountMergeRepository


class CompletionCollection:
    def __init__(self, document: dict[str, object]) -> None:
        self.document = document
        self.fail_update_once = False
        self.update_calls = 0

    async def find_one(self, query):
        return self.document if query.get("_id") == self.document["_id"] else None

    async def update_one(self, query, update):
        self.update_calls += 1
        if self.fail_update_once:
            self.fail_update_once = False
            raise OSError("journal update unavailable")
        if query.get("_id") == self.document["_id"]:
            self.document.update(update["$set"])
            return SimpleNamespace(matched_count=1)
        return SimpleNamespace(matched_count=0)


class CompletionFences:
    def __init__(self) -> None:
        self.fail_once = False
        self.completed_calls = 0

    async def mark_completed(self, *_args):
        self.completed_calls += 1
        if self.fail_once:
            self.fail_once = False
            raise OSError("fence update unavailable")


@pytest.mark.asyncio
async def test_merge_terminal_journal_retries_after_second_write_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal_id = PydanticObjectId()
    collection = CompletionCollection(
        {
            "_id": journal_id,
            "source_user_id": PydanticObjectId(),
            "status": AccountMergeStatus.MONGO_COMPLETE,
        }
    )
    collection.fail_update_once = True
    fences = CompletionFences()
    monkeypatch.setattr(
        AccountMergeDocument,
        "get_pymongo_collection",
        classmethod(lambda _cls: collection),
    )
    repository = AccountMergeRepository(fences)
    now = datetime.now(UTC)

    with pytest.raises(OSError, match="journal update"):
        await repository.mark_cleanup_completed(str(journal_id), now)
    assert collection.document["status"] == AccountMergeStatus.MONGO_COMPLETE
    assert fences.completed_calls == 1

    await repository.mark_cleanup_completed(str(journal_id), now)
    assert collection.document["status"] == AccountMergeStatus.COMPLETED
    assert fences.completed_calls == 2
    assert collection.document["retention_until"] is not None


@pytest.mark.asyncio
async def test_deletion_terminal_fence_failure_leaves_journal_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal_id = PydanticObjectId()
    collection = CompletionCollection(
        {
            "_id": journal_id,
            "user_id": PydanticObjectId(),
            "status": AccountDeletionStatus.DB_COMPLETE,
        }
    )
    fences = CompletionFences()
    fences.fail_once = True
    monkeypatch.setattr(
        AccountDeletionDocument,
        "get_pymongo_collection",
        classmethod(lambda _cls: collection),
    )
    repository = AccountDeletionRepository(fences)
    now = datetime.now(UTC)

    with pytest.raises(OSError, match="fence update"):
        await repository.mark_cleanup_completed(str(journal_id), now)
    assert collection.document["status"] == AccountDeletionStatus.DB_COMPLETE
    assert collection.update_calls == 0

    await repository.mark_cleanup_completed(str(journal_id), now)
    assert collection.document["status"] == AccountDeletionStatus.COMPLETED
    assert fences.completed_calls == 2
