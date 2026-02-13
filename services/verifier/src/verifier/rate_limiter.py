from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import redis

LUA_INCR_EXPIRE = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""

# ── Anti-replay Lua: atomic check-and-claim ──────────────
# Returns:
#   nil  → key was NEW (and is now claimed with fingerprint + "PENDING")
#   str  → existing value (JSON blob with fingerprint + cached decision)
LUA_REPLAY_CHECK = """
local existing = redis.call('GET', KEYS[1])
if existing then
    return existing
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
return nil
"""


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    count: int
    reason: str


@dataclass(frozen=True)
class ReplayCheckResult:
    is_new: bool
    cached_decision: dict | None = None
    fingerprint_match: bool = True


def _request_fingerprint(request_body: dict) -> str:
    """SHA-256 of canonical request body (excluding request_id)."""
    body = {k: v for k, v in request_body.items() if k != "request_id"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RateLimiter:
    def __init__(self, redis_url: str, timeout_s: float = 0.2):
        self._r = redis.Redis.from_url(
            redis_url, socket_timeout=timeout_s, socket_connect_timeout=timeout_s
        )
        self._script = self._r.register_script(LUA_INCR_EXPIRE)
        self._replay_script = self._r.register_script(LUA_REPLAY_CHECK)

    def check(self, key: str, limit: int, window_s: int) -> RateLimitResult:
        """
        Atomic counter with TTL.
        FAIL-CLOSED is handled by caller (on exception -> deny writes).
        """
        count = int(self._script(keys=[key], args=[str(window_s)]))
        if count <= limit:
            return RateLimitResult(True, count, "ok")
        return RateLimitResult(False, count, "limit_exceeded")

    # ── Anti-replay (idempotency) ────────────────────────

    def check_replay(
        self, request_id: str, request_body: dict, ttl_s: int = 86400
    ) -> ReplayCheckResult:
        """
        Idempotent anti-replay gate.

        - NEW request: claims the key with fingerprint + PENDING, returns is_new=True.
        - REPLAY, same payload: returns cached decision (if available).
        - REPLAY, different payload: returns fingerprint_match=False → caller must DENY.
        - Raises on Redis failure (caller decides fail-closed behaviour).
        """
        fp = _request_fingerprint(request_body)
        key = f"casf:req:{request_id}"
        claim_value = json.dumps({"fp": fp, "decision": None})

        result = self._replay_script(keys=[key], args=[claim_value, str(ttl_s)])

        if result is None:
            # New request — claimed successfully
            return ReplayCheckResult(is_new=True)

        # Replay — parse stored value
        stored = json.loads(result if isinstance(result, str) else result.decode("utf-8"))
        if stored["fp"] != fp:
            return ReplayCheckResult(is_new=False, fingerprint_match=False)

        return ReplayCheckResult(
            is_new=False,
            cached_decision=stored.get("decision"),
            fingerprint_match=True,
        )

    def store_decision(
        self, request_id: str, request_body: dict, decision: dict, ttl_s: int = 86400
    ) -> None:
        """
        Update the replay key with the actual decision (after processing).
        Uses SET XX KEEPTTL to preserve the original TTL.
        """
        fp = _request_fingerprint(request_body)
        key = f"casf:req:{request_id}"
        value = json.dumps({"fp": fp, "decision": decision})
        self._r.set(key, value, xx=True, keepttl=True)
