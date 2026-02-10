"""Tests for the /metrics endpoint and in-process counters (DoD: enterprise-grade)."""
from __future__ import annotations

import os
import uuid
from unittest.mock import MagicMock

os.environ.setdefault("PG_DSN", "dbname=casf user=casf password=casf host=localhost port=5432")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ANTI_REPLAY_ENABLED", "false")
os.environ.setdefault("CASF_DISABLE_AUDIT", "1")

from fastapi.testclient import TestClient

from src.verifier.main import app
from src.verifier.metrics import METRICS

client = TestClient(app)

# Shared payloads
_READ_PAYLOAD = {
    "tool": "cliniccloud.list_appointments",
    "mode": "READ_ONLY",
    "role": "receptionist",
    "subject": {"patient_id": "p1"},
    "args": {},
    "context": {"tenant_id": "t-demo"},
}

_WRITE_DENIED_PAYLOAD = {
    "tool": "cliniccloud.create_appointment",
    "mode": "READ_ONLY",
    "role": "receptionist",
    "subject": {"patient_id": "p1"},
    "args": {},
    "context": {"tenant_id": "t-demo"},
}


# ── /metrics endpoint ────────────────────────────────────


def test_metrics_endpoint_returns_200():
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]


def test_metrics_endpoint_contains_prometheus_format():
    r = client.get("/metrics")
    body = r.text
    assert "# TYPE" in body


def test_metrics_no_duplicate_type_lines():
    """Each metric name must have exactly one # TYPE line."""
    METRICS.reset()
    METRICS.inc("casf_verify_total")
    METRICS.inc("casf_verify_total")
    output = METRICS.render()
    assert output.count("# TYPE casf_verify_total") == 1


# ── casf_verify_total always increments ──────────────────


def test_verify_increments_total_counter():
    METRICS.reset()
    client.post("/verify", json={"request_id": str(uuid.uuid4()), **_READ_PAYLOAD})
    assert METRICS.get("casf_verify_total") == 1
    client.post("/verify", json={"request_id": str(uuid.uuid4()), **_READ_PAYLOAD})
    assert METRICS.get("casf_verify_total") == 2


# ── decision_total{ALLOW|DENY} matches responses ────────


def test_verify_allow_increments_decision_allow():
    METRICS.reset()
    r = client.post("/verify", json={"request_id": str(uuid.uuid4()), **_READ_PAYLOAD})
    assert r.json()["decision"] == "ALLOW"
    assert METRICS.get("casf_verify_decision_total", labels={"decision": "ALLOW"}) == 1
    assert METRICS.get("casf_verify_decision_total", labels={"decision": "DENY"}) == 0


def test_verify_deny_increments_decision_deny():
    METRICS.reset()
    r = client.post("/verify", json={"request_id": str(uuid.uuid4()), **_WRITE_DENIED_PAYLOAD})
    assert r.json()["decision"] == "DENY"
    assert METRICS.get("casf_verify_decision_total", labels={"decision": "DENY"}) == 1


# ── Histogram: duration is observed ─────────────────────


def test_verify_records_duration():
    METRICS.reset()
    client.post("/verify", json={"request_id": str(uuid.uuid4()), **_READ_PAYLOAD})
    output = METRICS.render()
    assert "casf_verify_duration_seconds_count" in output
    assert "casf_verify_duration_seconds_sum" in output
    assert "casf_verify_duration_seconds_bucket" in output


# ── Gauge: in_flight returns to zero after request ───────


def test_verify_in_flight_returns_to_zero():
    METRICS.reset()
    client.post("/verify", json={"request_id": str(uuid.uuid4()), **_READ_PAYLOAD})
    assert METRICS.gauge_get("casf_verify_in_flight") == 0


# ── Replay: hit increments + mismatch forces DENY ───────


def test_replay_hit_and_mismatch_counters():
    """Exercise replay via isolated client with FakeRedis."""
    from tests.test_anti_replay import _isolated_client

    METRICS.reset()
    rid = str(uuid.uuid4())
    payload = {"request_id": rid, **_READ_PAYLOAD}

    with _isolated_client() as (iso_client, _):
        # First request — new
        r1 = iso_client.post("/verify", json=payload)
        assert r1.json()["decision"] == "ALLOW"

        # Same request — replay hit (cached decision)
        r2 = iso_client.post("/verify", json=payload)
        assert r2.json()["decision"] == "ALLOW"
        assert METRICS.get("casf_replay_hit_total") >= 1

        # Same request_id, different payload — mismatch → DENY
        different_payload = {**payload, "subject": {"patient_id": "p999"}}
        r3 = iso_client.post("/verify", json=different_payload)
        assert r3.json()["decision"] == "DENY"
        assert METRICS.get("casf_replay_mismatch_total") >= 1


# ── fail_closed trigger correct when Redis down ─────────


def test_fail_closed_redis_trigger():
    """Redis failure on write → fail_closed{trigger=redis}."""
    from tests.test_anti_replay import _isolated_client

    METRICS.reset()
    with _isolated_client() as (iso_client, main_mod):
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
        r = iso_client.post("/verify", json=payload)
        assert r.json()["decision"] == "DENY"
        assert METRICS.get("casf_fail_closed_total", labels={"trigger": "redis"}) >= 1


# ── OPA error kind classification ────────────────────────


def test_opa_error_kind_label():
    """OPA timeout → opa_error_total{kind=timeout} + fail_closed{trigger=opa}."""
    from src.verifier.opa_client import OpaError
    from tests.test_anti_replay import _isolated_client

    METRICS.reset()

    def raise_timeout(*_a, **_kw):
        raise OpaError("timeout", "timed out")

    # Use isolated client so rate_limiter works (FakeRedis) — write tool that
    # doesn't hit SMS rate-limit so we actually reach the OPA path.
    with _isolated_client(ANTI_REPLAY_ENABLED="false") as (iso_client, main_mod):
        original = main_mod.opa.evaluate
        main_mod.opa.evaluate = raise_timeout
        try:
            payload = {
                "request_id": str(uuid.uuid4()),
                "tool": "cliniccloud.create_appointment",
                "mode": "ALLOW",
                "role": "doctor",
                "subject": {"patient_id": "p1"},
                "args": {},
                "context": {"tenant_id": "t-demo"},
            }
            r = iso_client.post("/verify", json=payload)
            assert r.json()["decision"] == "DENY"
            assert METRICS.get("casf_opa_error_total", labels={"kind": "timeout"}) >= 1
            assert METRICS.get("casf_fail_closed_total", labels={"trigger": "opa"}) >= 1
        finally:
            main_mod.opa.evaluate = original


# ── Render format ────────────────────────────────────────


def test_metrics_render_counters():
    METRICS.reset()
    METRICS.inc("casf_verify_total")
    METRICS.inc("casf_verify_decision_total", labels={"decision": "ALLOW"})

    output = METRICS.render()
    assert 'casf_verify_total 1' in output
    assert 'casf_verify_decision_total{decision="ALLOW"} 1' in output
    assert '# TYPE casf_verify_total counter' in output
    assert '# HELP casf_verify_total' in output


def test_metrics_render_gauge():
    METRICS.reset()
    METRICS.gauge_inc("casf_verify_in_flight")
    output = METRICS.render()
    assert "# TYPE casf_verify_in_flight gauge" in output
    assert "casf_verify_in_flight 1" in output


def test_metrics_render_histogram():
    METRICS.reset()
    METRICS.observe("casf_verify_duration_seconds", 0.042)
    output = METRICS.render()
    assert "# TYPE casf_verify_duration_seconds histogram" in output
    assert "casf_verify_duration_seconds_count" in output
    assert "casf_verify_duration_seconds_sum" in output


def test_metrics_reset_clears_all():
    METRICS.inc("casf_verify_total")
    METRICS.gauge_inc("casf_verify_in_flight")
    METRICS.observe("casf_verify_duration_seconds", 0.01)
    METRICS.reset()
    assert METRICS.get("casf_verify_total") == 0
    assert METRICS.gauge_get("casf_verify_in_flight") == 0
