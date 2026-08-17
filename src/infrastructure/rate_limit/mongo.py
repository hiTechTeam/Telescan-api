import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from src.domain.errors import RateLimitExceeded
from src.infrastructure.mongodb.documents import RateLimitDocument


class MongoRateLimiter:
    """Distributed fixed-window limiter backed by the application MongoDB."""

    def __init__(
        self,
        collection: Any | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._collection_override = collection
        self._clock = clock or (lambda: datetime.now(UTC))

    async def check(self, key: str, limit: int, window_seconds: int) -> None:
        if limit < 1 or window_seconds < 1:
            raise ValueError("Rate-limit values must be positive")

        now = self._clock()
        timestamp = int(now.timestamp())
        bucket = timestamp // window_seconds
        scope_digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        scope_key = f"{scope_digest}:{window_seconds}:{bucket}"
        window_end = (bucket + 1) * window_seconds
        expires_at = datetime.fromtimestamp(window_end + window_seconds, UTC)
        collection = self._collection_override
        if collection is None:
            collection = RateLimitDocument.get_pymongo_collection()

        update = {
            "$inc": {"hits": 1},
            "$setOnInsert": {
                "scope_key": scope_key,
                "expires_at": expires_at,
            },
        }
        try:
            record = await collection.find_one_and_update(
                {"scope_key": scope_key},
                update,
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            # Concurrent first requests can race on the unique scope index.
            record = await collection.find_one_and_update(
                {"scope_key": scope_key},
                update,
                upsert=False,
                return_document=ReturnDocument.AFTER,
            )

        if record is None or int(record["hits"]) > limit:
            raise RateLimitExceeded(max(1, window_end - timestamp))
