"""Tests for the /metrics endpoint and in-process counters."""
from __future__ import annotations

import os
import uuid

os.environ.setdefault("PG_DSN", "dbname=casf user=casf password=casf host=localhost port=5432")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ANTI_REPLAY_ENABLED", "false")
os.environ.setdefault("CASF_DISABLE_AUDIT", "1")

from fastapi.testclient import TestClient

from src.verifier.main import app
from src.verifier.metrics import METRICS

client = TestClient(app)


# ── /metrics endpoint ────────────────────────────────────


def test_metrics_endpoint_returns_200():
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]


def test_metrics_endpoint_contains_prometheus_format():
    r = client.get("/metrics")
    body = r.text
    assert "# TYPE" in body


# ── Counter increments ───────────────────────────────────


def test_verify_increments_total_counter():
    METRICS.reset()
    payload = {
        "request_id": str(uuid.uuid4()),
        "tool": "cliniccloud.list_appointments",
        "mode": "READ_ONLY",
        "role": "receptionist",
        "subject": {"patient_id": "p1"},
        "args": {},
        "context": {"tenant_id": "t-demo"},
    }
    client.post("/verify", json=payload)
    assert METRICS.get("casf_verify_total") >= 1


def test_verify_allow_increments_decision_counter():
    METRICS.reset()
    payload = {
        "request_id": str(uuid.uuid4()),
        "tool": "cliniccloud.list_appointments",
        "mode": "READ_ONLY",
        "role": "receptionist",
        "subject": {"patient_id": "p1"},
        "args": {},
        "context": {"tenant_id": "t-demo"},
    }
    client.post("/verify", json=payload)
    assert METRICS.get("casf_verify_decision_total", labels={"decision": "ALLOW"}) >= 1


def test_verify_deny_increments_decision_counter():
    METRICS.reset()
    payload = {
        "request_id": str(uuid.uuid4()),
        "tool": "cliniccloud.create_appointment",
        "mode": "READ_ONLY",
        "role": "receptionist",
        "subject": {"patient_id": "p1"},
        "args": {},
        "context": {"tenant_id": "t-demo"},
    }
    client.post("/verify", json=payload)
    assert METRICS.get("casf_verify_decision_total", labels={"decision": "DENY"}) >= 1


# ── Metrics render format ────────────────────────────────


def test_metrics_render_format():
    METRICS.reset()
    METRICS.inc("casf_verify_total")
    METRICS.inc("casf_verify_decision_total", labels={"decision": "ALLOW"})

    output = METRICS.render()
    assert 'casf_verify_total 1' in output
    assert 'casf_verify_decision_total{decision="ALLOW"} 1' in output
    assert '# TYPE casf_verify_total counter' in output
    assert '# HELP casf_verify_total' in output


def test_metrics_reset_clears_all():
    METRICS.inc("casf_verify_total")
    METRICS.reset()
    assert METRICS.get("casf_verify_total") == 0
