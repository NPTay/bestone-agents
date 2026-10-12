from collections import defaultdict, deque
from datetime import datetime

from app import clock


class RateLimiter:
    """In-memory sliding-window limiter (single process; fine for one uvicorn worker)."""

    def __init__(self, max_hits: int = 10, window_s: int = 60) -> None:
        self.max_hits = max_hits
        self.window_s = window_s
        self._hits: defaultdict[str, deque[datetime]] = defaultdict(deque)
        self._last_sweep: datetime | None = None

    def _prune(self, hits: deque[datetime], now: datetime) -> None:
        while hits and (now - hits[0]).total_seconds() >= self.window_s:
            hits.popleft()

    def _sweep(self, now: datetime) -> None:
        """Drop stale keys; runs at most once per window."""
        last = self._last_sweep
        if last is not None and (now - last).total_seconds() < self.window_s:
            return
        self._last_sweep = now
        for key in list(self._hits):
            self._prune(self._hits[key], now)
            if not self._hits[key]:
                del self._hits[key]

    def key_count(self) -> int:
        return len(self._hits)

    def hit(self, key: str) -> bool:
        """Record a hit; return False when the key has exceeded the limit."""
        now = clock.utcnow()
        self._sweep(now)
        hits = self._hits[key]
        self._prune(hits, now)
        if len(hits) >= self.max_hits:
            return False
        hits.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()
        self._last_sweep = None


login_limiter = RateLimiter(max_hits=10, window_s=60)
