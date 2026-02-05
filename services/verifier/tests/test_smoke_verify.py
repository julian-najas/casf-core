from fastapi.testclient import TestClient
from verifier.main import app

client = TestClient(app)

BASE_CTX = {"timestamp": "2026-02-05T10:00:00Z", "source": "agent"}

def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

def test_read_only_denies_write():
    payload = {
        "request_id": "t1",
        "tool": "cliniccloud.create_appointment",
        "mode": "READ_ONLY",
        "role": "receptionist",
        "subject": {"patient_id": "p1"},
        "args": {},
        "context": BASE_CTX,
    }
    r = client.post("/verify", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "DENY"
    assert "Inv_NoWriteSafe" in body["violations"]

def test_read_only_allows_list_appointments_aggregated():
    payload = {
        "request_id": "t2",
        "tool": "cliniccloud.list_appointments",
        "mode": "READ_ONLY",
        "role": "receptionist",
        "subject": {"patient_id": "p1"},
        "args": {},
        "context": BASE_CTX,
    }
    r = client.post("/verify", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "ALLOW"
    assert "slots_aggregated" in body["allowed_outputs"]
