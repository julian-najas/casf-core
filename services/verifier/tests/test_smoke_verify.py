import os
import uuid

os.environ.setdefault("PG_DSN", "dbname=casf user=casf password=casf host=localhost port=5432")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPA_URL", "http://localhost:8181")

from importlib import reload
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.verifier.opa_client import OpaDecision


def _get_client():
    """Fresh app/client to avoid cross-test env/module contamination."""
    os.environ["ANTI_REPLAY_ENABLED"] = "false"
    os.environ["CASF_DISABLE_AUDIT"] = "1"

    import src.verifier.settings as settings_mod

    reload(settings_mod)
    import src.verifier.main as main_mod

    reload(main_mod)
    return TestClient(main_mod.app), main_mod


BASE_CTX = {"timestamp": "2026-02-05T10:00:00Z", "source": "agent", "tenant_id": "tenant_1"}


def test_health_ok():
    client, _main = _get_client()
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_read_only_denies_write():
    client, main_mod = _get_client()
    payload = {
        "request_id": str(uuid.uuid4()),
        "tool": "cliniccloud.create_appointment",
        "mode": "READ_ONLY",
        "role": "receptionist",
        "subject": {"patient_id": "p1"},
        "args": {},
        "context": BASE_CTX,
    }

    # Simulate OPA decision locally (no external dependency)
    with patch.object(
        main_mod.opa,
        "evaluate",
        return_value=OpaDecision(allow=False, violations=["Mode_ReadOnly_NoWrite"]),
    ):
        r = client.post("/verify", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "DENY"
    assert "Mode_ReadOnly_NoWrite" in body["violations"]


def test_read_only_allows_list_appointments_aggregated():
    client, main_mod = _get_client()
    payload = {
        "request_id": str(uuid.uuid4()),
        "tool": "cliniccloud.list_appointments",
        "mode": "READ_ONLY",
        "role": "receptionist",
        "subject": {"patient_id": "p1"},
        "args": {},
        "context": BASE_CTX,
    }

    # Simulate OPA allow locally (no external dependency)
    with patch.object(
        main_mod.opa,
        "evaluate",
        return_value=OpaDecision(allow=True, violations=[]),
    ):
        r = client.post("/verify", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "ALLOW"
    assert "slots_aggregated" in body["allowed_outputs"]
