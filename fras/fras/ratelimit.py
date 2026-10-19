"""Token-bucket rate limiter kept in memory (single-node deployments).

For multi-node deployments the same interface would be backed by Redis.
"""

from __future__ import annotations

import threading
import time


class RateLimiter:
    def __init__(self):
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, capacity: int, refill_per_s: float) -> int:
        """Consume one token. Returns 0 if allowed, else seconds to wait."""
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (float(capacity), now))
            tokens = min(capacity, tokens + (now - last) * refill_per_s)
            if tokens < 1:
                self._buckets[key] = (tokens, now)
                return max(1, int((1 - tokens) / refill_per_s))
            self._buckets[key] = (tokens - 1, now)
            if len(self._buckets) > 50_000:
                self._buckets.clear()
            return 0


limiter = RateLimiter()

# (capacity, refill per second)
POLICIES = {
    "login": (10, 10 / 60),        # 10 per minute per IP
    "write": (120, 2.0),           # 120 burst, 2/s sustained per user
    "read": (600, 10.0),
    "device": (600, 20.0),
    "public": (30, 0.5),
}
