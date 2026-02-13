"""
Tests for /healthz readiness probe.
Requires Postgres, Redis, and OPA running locally.
"""

import os

os.environ.setdefault("PG_DSN", "dbname=casf user=casf password=casf host=localhost port=5432")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPA_URL", "http://localhost:8181")
os.environ.setdefault("CASF_DISABLE_AUDIT", "1")


def _get_client():
    """Get a fresh TestClient, reloading modules to avoid stale state."""
    from importlib import reload

    import src.verifier.settings as settings_mod

    reload(settings_mod)
    import src.verifier.main as main_mod

    reload(main_mod)
    from fastapi.testclient import TestClient

    return TestClient(main_mod.app)


def test_healthz_returns_ok_when_all_deps_up():
    """All dependencies healthy -> 200 + status ok."""
    client = _get_client()
    r = client.get("/healthz")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["status"] == "ok"
    assert body["checks"]["postgres"] == "ok"
    assert body["checks"]["redis"] == "ok"
    assert body["checks"]["opa"] == "ok"


def test_health_liveness_still_works():
    """Liveness probe (/health) is independent and always 200."""
    client = _get_client()
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
