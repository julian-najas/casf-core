"""
Shared test helpers for casf-verifier.

Centralises helpers that were duplicated across test files:
  - FakeRedis (Lua-script emulation)
  - get_client / isolated_client (module-reload based TestClient factories)
  - make_request / make_response (request/response builders)
  - Shared payload constants

Import in tests as:
    from helpers import get_client, FakeRedis, isolated_client, ...
"""

from __future__ import annotations

import contextlib
import os
import uuid
from importlib import reload
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.verifier.models import VerifyRequestV1, VerifyResponseV1


# ── FakeRedis ────────────────────────────────────────────


class FakeRedis:
    """Minimal stand-in for redis.Redis with SET NX / GET / XX KEEPTTL + Lua scripts."""

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
            return None
        self._store[key] = value
        return True

    def get(self, key: str) -> bytes | None:
        v = self._store.get(key)
        return v.encode("utf-8") if v is not None else None

    def register_script(self, script: str) -> MagicMock:
        """Return a callable that simulates the Lua script via Python."""
        redis_ref = self

        if "INCR" in script:

            def lua_incr(keys, args):
                k = keys[0]
                val = int(redis_ref._store.get(k, "0")) + 1
                redis_ref._store[k] = str(val)
                return val

            return lua_incr

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


# ── TestClient factories ─────────────────────────────────


def get_client(
    *,
    anti_replay: bool = False,
    disable_audit: bool = True,
) -> tuple[TestClient, object]:
    """
    Get a fresh TestClient, reloading modules to avoid stale state.

    Args:
        anti_replay: enable anti-replay gate (default False for simplicity).
        disable_audit: skip Postgres audit writes (default True for unit tests).

    Returns:
        (TestClient, main_mod) — main_mod is useful for patching opa/rl.
    """
    if not anti_replay:
        os.environ["ANTI_REPLAY_ENABLED"] = "false"
    if disable_audit:
        os.environ["CASF_DISABLE_AUDIT"] = "1"

    import src.verifier.settings as settings_mod

    reload(settings_mod)
    import src.verifier.main as main_mod

    reload(main_mod)
    return TestClient(main_mod.app), main_mod


@contextlib.contextmanager
def isolated_client(**extra_env):
    """
    Context-managed TestClient with FakeRedis + isolated env.

    On exit, restores os.environ and reloads modules so later tests
    aren't poisoned. Yields (TestClient, main_mod).
    """
    env_overrides = {
        "REDIS_URL": "redis://localhost:6379/0",
        "CASF_DISABLE_AUDIT": "1",
        "ANTI_REPLAY_ENABLED": "true",
        **extra_env,
    }
    saved = {k: os.environ.get(k) for k in env_overrides}
    os.environ.update(env_overrides)

    try:
        with patch("src.verifier.rate_limiter.redis.Redis.from_url", FakeRedis.from_url):
            import src.verifier.settings as settings_mod

            reload(settings_mod)
            import src.verifier.main as main_mod

            reload(main_mod)
            yield TestClient(main_mod.app), main_mod
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        import src.verifier.settings as s

        reload(s)
        import src.verifier.main as m

        reload(m)


# ── Request / Response builders ──────────────────────────


def make_request(**overrides) -> VerifyRequestV1:
    """Build a VerifyRequestV1 with sensible defaults."""
    defaults: dict = dict(
        request_id=str(uuid.uuid4()),
        tool="twilio.send_sms",
        mode="ALLOW",
        role="receptionist",
        subject={"patient_id": "p1"},
        args={"to": "+34600000000", "template_id": "t1"},
        context={"tenant_id": "t-demo"},
    )
    defaults.update(overrides)
    return VerifyRequestV1(**defaults)


def make_response(**overrides) -> VerifyResponseV1:
    """Build a VerifyResponseV1 with sensible defaults."""
    defaults: dict = dict(
        decision="ALLOW",
        violations=[],
        allowed_outputs=[],
        reason="OK",
    )
    defaults.update(overrides)
    return VerifyResponseV1(**defaults)


# ── Shared payload constants ─────────────────────────────

SAMPLE_READ_PAYLOAD = {
    "tool": "cliniccloud.list_appointments",
    "mode": "READ_ONLY",
    "role": "receptionist",
    "subject": {"patient_id": "p1"},
    "args": {},
    "context": {"tenant_id": "t-demo"},
}

SAMPLE_WRITE_PAYLOAD = {
    "tool": "cliniccloud.create_appointment",
    "mode": "ALLOW",
    "role": "receptionist",
    "subject": {"patient_id": "p1"},
    "args": {},
    "context": {"tenant_id": "t-demo"},
}

SAMPLE_WRITE_DENIED_PAYLOAD = {
    "tool": "cliniccloud.create_appointment",
    "mode": "READ_ONLY",
    "role": "receptionist",
    "subject": {"patient_id": "p1"},
    "args": {},
    "context": {"tenant_id": "t-demo"},
}
