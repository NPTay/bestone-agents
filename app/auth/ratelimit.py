from collections import defaultdict, deque
from datetime import datetime

from app import clock


class RateLimiter:
    """In-memory sliding-window limiter (single process; fine for one uvicorn worker)."""

    def __init__(self, max_hits: int = 10, window_s: int = 60) -> None:
        self.max_hits = max_hits
        self.window_s = window_s
        self._hits: defaultdict[str, deque[datetime]] = defaultdict(deque)

    def hit(self, key: str) -> bool:
        """Record a hit; return False when the key has exceeded the limit."""
        now = clock.utcnow()
        hits = self._hits[key]
        while hits and (now - hits[0]).total_seconds() >= self.window_s:
            hits.popleft()
        if len(hits) >= self.max_hits:
            return False
        hits.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


login_limiter = RateLimiter(max_hits=10, window_s=60)
