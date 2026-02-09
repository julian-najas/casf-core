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
