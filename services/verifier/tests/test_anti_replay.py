"""Tests for anti-replay idempotency gate (Redis + cached decision)."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from src.verifier.rate_limiter import RateLimiter

# ── FakeRedis with Lua-script support ────────────────────


class FakeRedis:
    """Minimal stand-in for redis.Redis with SET NX / GET / XX KEEPTTL."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        ex: int | None = None,
        xx: bool = False,
        keepttl: bool = False,
    ) -> bool | None:
        if xx:
            if key not in self._store:
                return None
            self._store[key] = value
            return True
        if nx and key in self._store:
            return None  # SET NX fails
        self._store[key] = value
        return True

    def get(self, key: str) -> bytes | None:
        v = self._store.get(key)
        return v.encode("utf-8") if v is not None else None

    def register_script(self, script: str) -> MagicMock:
        """Return a callable that simulates the Lua script via Python."""
        redis_ref = self

        if "INCR" in script:
            # rate-limit script
            def lua_incr(keys, args):
                k = keys[0]
                val = int(redis_ref._store.get(k, "0")) + 1
                redis_ref._store[k] = str(val)
                return val
            return lua_incr

        # replay-check script
        def lua_replay(keys, args):
            k = keys[0]
            existing = redis_ref._store.get(k)
            if existing is not None:
                return existing.encode("utf-8")
            redis_ref._store[k] = args[0]
            return None

        return lua_replay

    @classmethod
    def from_url(cls, _url: str, **_kw: object) -> FakeRedis:
        return cls()


def _make_rl() -> RateLimiter:
    """Build a RateLimiter backed by FakeRedis."""
    with patch("redis.Redis.from_url", FakeRedis.from_url):
        return RateLimiter("redis://fake:6379/0")


SAMPLE_BODY = {
    "request_id": "req-1",
    "tool": "cliniccloud.list_appointments",
    "mode": "READ_ONLY",
    "role": "receptionist",
    "subject": {"patient_id": "p1"},
    "args": {},
    "context": {"tenant_id": "t-demo"},
}


# ── Unit tests: check_replay ─────────────────────────────


def test_first_request_is_new():
    rl = _make_rl()
    result = rl.check_replay("req-1", SAMPLE_BODY)
    assert result.is_new is True


def test_same_request_returns_cached_decision():
    """Same request_id + same payload → returns cached decision (idempotent)."""
    rl = _make_rl()

    # First call — new
    r1 = rl.check_replay("req-1", SAMPLE_BODY)
    assert r1.is_new is True

    # Store decision
    decision = {"decision": "ALLOW", "violations": [], "allowed_outputs": [], "reason": "OK"}
    rl.store_decision("req-1", SAMPLE_BODY, decision)

    # Second call — replay with cached decision
    r2 = rl.check_replay("req-1", SAMPLE_BODY)
    assert r2.is_new is False
    assert r2.fingerprint_match is True
    assert r2.cached_decision == decision


def test_different_payload_same_request_id_is_mismatch():
    """Same request_id + different payload → fingerprint mismatch → DENY."""
    rl = _make_rl()

    r1 = rl.check_replay("req-1", SAMPLE_BODY)
    assert r1.is_new is True

    different_body = {**SAMPLE_BODY, "tool": "twilio.send_sms", "mode": "ALLOW"}
    r2 = rl.check_replay("req-1", different_body)
    assert r2.is_new is False
    assert r2.fingerprint_match is False


def test_different_request_ids_are_both_new():
    rl = _make_rl()
    assert rl.check_replay("req-a", SAMPLE_BODY).is_new is True
    assert rl.check_replay("req-b", SAMPLE_BODY).is_new is True


def test_redis_failure_propagates():
    """check_replay must raise so the caller can decide fail-closed."""
    rl = _make_rl()
    rl._replay_script = MagicMock(side_effect=ConnectionError("redis down"))
    try:
        rl.check_replay("req-x", SAMPLE_BODY)
        raise AssertionError("Should have raised")
    except ConnectionError:
        pass  # expected


def test_pending_decision_returned_as_none():
    """If decision hasn't been stored yet, cached_decision is None."""
    rl = _make_rl()

    rl.check_replay("req-1", SAMPLE_BODY)  # claim

    # Second call without store_decision
    r2 = rl.check_replay("req-1", SAMPLE_BODY)
    assert r2.is_new is False
    assert r2.fingerprint_match is True
    assert r2.cached_decision is None


# ── Integration tests: /verify endpoint ──────────────────


def _make_client():
    """Create a test client with FakeRedis and audit disabled."""
    import os
    os.environ.setdefault("PG_DSN", "postgresql://user:pass@localhost/db")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    os.environ["CASF_DISABLE_AUDIT"] = "1"
    os.environ["ANTI_REPLAY_ENABLED"] = "true"

    with patch("src.verifier.rate_limiter.redis.Redis.from_url", FakeRedis.from_url):
        from importlib import reload

        import src.verifier.settings as settings_mod
        reload(settings_mod)
        import src.verifier.main as main_mod
        reload(main_mod)
        from fastapi.testclient import TestClient
        return TestClient(main_mod.app)


def test_verify_replay_returns_cached_decision():
    """Same request_id twice → 2nd returns same decision (200, idempotent)."""
    client = _make_client()

    rid = str(uuid.uuid4())
    payload = {
        "request_id": rid,
        "tool": "cliniccloud.list_appointments",
        "mode": "READ_ONLY",
        "role": "receptionist",
        "subject": {"patient_id": "p1"},
        "args": {},
        "context": {"tenant_id": "t-demo"},
    }

    r1 = client.post("/verify", json=payload)
    assert r1.status_code == 200, f"Expected 200, got {r1.status_code}: {r1.text}"
    d1 = r1.json()

    # Second call, same payload → cached decision returned
    r2 = client.post("/verify", json=payload)
    assert r2.status_code == 200, f"Expected 200, got {r2.status_code}: {r2.text}"
    d2 = r2.json()

    assert d2["decision"] == d1["decision"]
    assert d2["violations"] == d1["violations"]


def test_verify_replay_mismatch_returns_deny():
    """Same request_id + different payload → DENY."""
    client = _make_client()

    rid = str(uuid.uuid4())
    payload1 = {
        "request_id": rid,
        "tool": "cliniccloud.list_appointments",
        "mode": "READ_ONLY",
        "role": "receptionist",
        "subject": {"patient_id": "p1"},
        "args": {},
        "context": {"tenant_id": "t-demo"},
    }

    r1 = client.post("/verify", json=payload1)
    assert r1.status_code == 200

    # Different payload, same request_id
    payload2 = {**payload1, "subject": {"patient_id": "p2"}}
    r2 = client.post("/verify", json=payload2)
    assert r2.status_code == 200  # not 409 — returns structured DENY
    d2 = r2.json()
    assert d2["decision"] == "DENY"
    assert "Inv_ReplayPayloadMismatch" in d2["violations"]


def test_verify_redis_down_write_tool_denies():
    """Redis unavailable + write tool → DENY (fail-closed)."""
    import os
    os.environ.setdefault("PG_DSN", "postgresql://user:pass@localhost/db")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    os.environ["CASF_DISABLE_AUDIT"] = "1"
    os.environ["ANTI_REPLAY_ENABLED"] = "true"

    with patch("src.verifier.rate_limiter.redis.Redis.from_url", FakeRedis.from_url):
        from importlib import reload

        import src.verifier.settings as settings_mod
        reload(settings_mod)
        import src.verifier.main as main_mod
        reload(main_mod)
        from fastapi.testclient import TestClient
        client = TestClient(main_mod.app)

        # Break the replay check
        main_mod.rl._replay_script = MagicMock(side_effect=ConnectionError("redis down"))

        payload = {
            "request_id": str(uuid.uuid4()),
            "tool": "twilio.send_sms",
            "mode": "ALLOW",
            "role": "nurse",
            "subject": {"patient_id": "p1"},
            "args": {"phone": "+1234567890", "body": "test"},
            "context": {"tenant_id": "t-demo"},
        }

        r = client.post("/verify", json=payload)
        assert r.status_code == 200
        d = r.json()
        assert d["decision"] == "DENY"
        assert "FAIL_CLOSED" in d["violations"]
