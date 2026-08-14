import asyncio
from collections import defaultdict, deque
from time import monotonic

from src.domain.errors import RateLimitExceeded


class InMemoryRateLimiter:
    """Small single-process limiter; production can inject a Redis adapter."""

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
                raise RateLimitExceeded()
            events.append(now)
