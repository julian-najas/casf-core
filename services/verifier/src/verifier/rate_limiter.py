from __future__ import annotations

from dataclasses import dataclass

import redis

LUA_INCR_EXPIRE = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""

# Anti-replay: SET NX EX — returns 1 if key was NEW, 0 if already seen
REPLAY_TTL_S = 86400  # 24 hours


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    count: int
    reason: str


class RateLimiter:
    def __init__(self, redis_url: str, timeout_s: float = 0.2):
        self._r = redis.Redis.from_url(redis_url, socket_timeout=timeout_s, socket_connect_timeout=timeout_s)
        self._script = self._r.register_script(LUA_INCR_EXPIRE)

    def check(self, key: str, limit: int, window_s: int) -> RateLimitResult:
        """
        Atomic counter with TTL.
        FAIL-CLOSED is handled by caller (on exception -> deny writes).
        """
        count = int(self._script(keys=[key], args=[str(window_s)]))
        if count <= limit:
            return RateLimitResult(True, count, "ok")
        return RateLimitResult(False, count, "limit_exceeded")

    def check_replay(self, request_id: str, ttl_s: int = REPLAY_TTL_S) -> bool:
        """
        Anti-replay gate.  Returns True if this request_id is NEW (first-seen).
        Returns False if it was already processed (replay).
        Uses SET NX EX — atomic, single round-trip.
        Raises on Redis failure (caller decides fail-closed behaviour).
        """
        key = f"replay:{request_id}"
        return bool(self._r.set(key, "1", nx=True, ex=ttl_s))
