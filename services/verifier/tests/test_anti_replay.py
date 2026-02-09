"""Tests for anti-replay gate (Redis SET NX EX)."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from src.verifier.rate_limiter import RateLimiter

# ── Unit tests: check_replay method ──────────────────────


class FakeRedis:
    """Minimal stand-in for redis.Redis with SET NX support."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool | None:
        if nx and key in self._store:
            return None  # already exists → SET NX returns None
        self._store[key] = value
        return True

    # stubs so RateLimiter.__init__ doesn't crash
    def register_script(self, _script: str) -> MagicMock:
        return MagicMock()

    @classmethod
    def from_url(cls, _url: str, **_kw: object) -> FakeRedis:
        return cls()


def _make_rl() -> RateLimiter:
    """Build a RateLimiter backed by FakeRedis."""
    with patch("redis.Redis.from_url", FakeRedis.from_url):
        return RateLimiter("redis://fake:6379/0")


def test_first_request_is_new():
    rl = _make_rl()
    assert rl.check_replay("req-1") is True


def test_same_request_id_is_replay():
    rl = _make_rl()
    assert rl.check_replay("req-1") is True
    assert rl.check_replay("req-1") is False


def test_different_request_ids_are_both_new():
    rl = _make_rl()
    assert rl.check_replay("req-a") is True
    assert rl.check_replay("req-b") is True


def test_redis_failure_propagates():
    """check_replay must raise so the caller can decide fail-closed."""
    rl = _make_rl()
    rl._r.set = MagicMock(side_effect=ConnectionError("redis down"))
    try:
        rl.check_replay("req-x")
        raise AssertionError("Should have raised")
    except ConnectionError:
        pass  # expected


# ── Integration tests: /verify endpoint replay behaviour ─


def test_verify_replay_returns_409():
    """Same request_id twice → 409 Conflict."""
    import os

    os.environ.setdefault("PG_DSN", "postgresql://user:pass@localhost/db")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    os.environ["CASF_DISABLE_AUDIT"] = "1"

    # Patch RateLimiter at module level before importing app
    with patch("src.verifier.rate_limiter.redis.Redis.from_url", FakeRedis.from_url):
        # Re-import to pick up patched RateLimiter
        from importlib import reload

        import src.verifier.main as main_mod

        reload(main_mod)
        from fastapi.testclient import TestClient

        client = TestClient(main_mod.app)

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

        # First call → should pass rules (READ_ONLY + list_appointments = ALLOW)
        r1 = client.post("/verify", json=payload)
        assert r1.status_code == 200, f"Expected 200, got {r1.status_code}: {r1.text}"

        # Second call, same request_id → 409 replay
        r2 = client.post("/verify", json=payload)
        assert r2.status_code == 409, f"Expected 409, got {r2.status_code}: {r2.text}"
        assert "Replay" in r2.json()["detail"]
