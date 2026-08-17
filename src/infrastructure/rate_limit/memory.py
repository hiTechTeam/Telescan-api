import asyncio
from collections import defaultdict, deque
from time import monotonic

from src.domain.errors import RateLimitExceeded


class InMemoryRateLimiter:
    """Small single-process limiter for tests and local dependency overrides."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = monotonic()
        cutoff = now - window_seconds
        async with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, int(events[0] + window_seconds - now))
                raise RateLimitExceeded(retry_after)
            events.append(now)
