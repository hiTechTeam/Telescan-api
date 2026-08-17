from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.domain.errors import RateLimitExceeded
from src.infrastructure.rate_limit import MongoRateLimiter


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class FakeCollection:
    def __init__(self) -> None:
        self.hits: dict[str, int] = {}
        self.expires_at: dict[str, datetime] = {}

    async def find_one_and_update(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        **_: Any,
    ) -> dict[str, Any]:
        scope = query["scope_key"]
        self.hits[scope] = self.hits.get(scope, 0) + update["$inc"]["hits"]
        self.expires_at.setdefault(scope, update["$setOnInsert"]["expires_at"])
        return {"scope_key": scope, "hits": self.hits[scope]}


@pytest.mark.asyncio
async def test_mongo_limiter_is_distributed_hashed_and_resets_by_window() -> None:
    clock = MutableClock()
    collection = FakeCollection()
    limiter = MongoRateLimiter(collection=collection, clock=clock)
    raw_scope = "auth-link:ip:203.0.113.20"

    await limiter.check(raw_scope, limit=2, window_seconds=60)
    await limiter.check(raw_scope, limit=2, window_seconds=60)
    with pytest.raises(RateLimitExceeded) as error:
        await limiter.check(raw_scope, limit=2, window_seconds=60)

    assert error.value.retry_after_seconds == 60
    assert len(collection.hits) == 1
    first_scope = next(iter(collection.hits))
    assert raw_scope not in first_scope
    assert collection.expires_at[first_scope].tzinfo is UTC

    clock.now += timedelta(seconds=60)
    await limiter.check(raw_scope, limit=2, window_seconds=60)
    assert len(collection.hits) == 2


@pytest.mark.asyncio
async def test_mongo_limiter_rejects_invalid_configuration() -> None:
    limiter = MongoRateLimiter(collection=FakeCollection())

    with pytest.raises(ValueError):
        await limiter.check("scope", limit=0, window_seconds=60)
    with pytest.raises(ValueError):
        await limiter.check("scope", limit=1, window_seconds=0)
