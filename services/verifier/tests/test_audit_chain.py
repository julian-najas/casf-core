"""
Integration tests for audit hash-chain (requires Postgres running).
Run with:
    $env:PG_DSN="dbname=casf user=casf password=casf host=localhost port=5432"
    python -m pytest tests/test_audit_chain.py -v
"""

import os
import uuid

import psycopg2
import pytest

from src.verifier.audit import (
    append_audit_event,
    compute_hash,
    verify_chain,
)
from src.verifier.models import (
    AuditEventV1,
    VerifyRequestV1,
    VerifyResponseV1,
)

PG_DSN = os.environ.get("PG_DSN", "dbname=casf user=casf password=casf host=localhost port=5432")


# ── Fixtures ─────────────────────────────────────────────


def _clean_audit_table():
    """Truncate audit_events so each test starts with a clean chain."""
    conn = psycopg2.connect(PG_DSN)
    try:
        with conn, conn.cursor() as cur:
            cur.execute("TRUNCATE audit_events RESTART IDENTITY;")
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def clean_db():
    _clean_audit_table()
    yield
    _clean_audit_table()


def _mk_req(**overrides) -> VerifyRequestV1:
    defaults = dict(
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


def _mk_res(**overrides) -> VerifyResponseV1:
    defaults = dict(
        decision="ALLOW",
        violations=[],
        allowed_outputs=[],
        reason="OK",
    )
    defaults.update(overrides)
    return VerifyResponseV1(**defaults)


# ── Unit: compute_hash is deterministic ──────────────────


def test_compute_hash_deterministic():
    kwargs = dict(
        request_id="r1",
        event_id="e1",
        ts="2026-02-09T12:00:00.000000Z",
        actor="role:receptionist",
        action="twilio.send_sms",
        decision="ALLOW",
        payload={"a": 1, "b": 2},
        prev_hash="",
    )
    h1 = compute_hash(**kwargs)
    h2 = compute_hash(**kwargs)
    assert h1 == h2
    assert len(h1) == 64  # sha-256 hex


def test_compute_hash_changes_with_any_field():
    base = dict(
        request_id="r1",
        event_id="e1",
        ts="2026-02-09T12:00:00.000000Z",
        actor="role:receptionist",
        action="twilio.send_sms",
        decision="ALLOW",
        payload={"a": 1},
        prev_hash="",
    )
    h_base = compute_hash(**base)
    # Flip every field and check the hash changes
    for field, alt in [
        ("request_id", "r2"),
        ("event_id", "e2"),
        ("ts", "2026-02-09T13:00:00.000000Z"),
        ("actor", "role:doctor"),
        ("action", "stripe.generate_invoice"),
        ("decision", "DENY"),
        ("payload", {"a": 2}),
        ("prev_hash", "abc"),
    ]:
        modified = {**base, field: alt}
        assert compute_hash(**modified) != h_base, f"hash did not change when {field} was modified"


# ── Integration: genesis event ───────────────────────────


def test_genesis_event_has_empty_prev_hash():
    req = _mk_req()
    res = _mk_res()
    evt = append_audit_event(PG_DSN, req, res)

    assert evt.prev_hash == ""
    assert len(evt.hash) == 64
    assert evt.actor == f"role:{req.role}"
    assert evt.action == req.tool


# ── Integration: chain of 2 events ──────────────────────


def test_chain_two_events_linked():
    req1 = _mk_req()
    res1 = _mk_res()
    evt1 = append_audit_event(PG_DSN, req1, res1)

    req2 = _mk_req()
    res2 = _mk_res(decision="DENY", violations=["Inv_NoSmsBurst"])
    evt2 = append_audit_event(PG_DSN, req2, res2)

    # Second event's prev_hash == first event's hash
    assert evt2.prev_hash == evt1.hash
    # Hashes are different
    assert evt1.hash != evt2.hash


# ── Integration: verify_chain passes on valid data ───────


def test_verify_chain_valid():
    evts = []
    for _i in range(3):
        req = _mk_req()
        res = _mk_res()
        evts.append(append_audit_event(PG_DSN, req, res))

    ok, idx = verify_chain(evts)
    assert ok is True
    assert idx is None


# ── Integration: verify_chain detects tampering ──────────


def test_verify_chain_detects_tampered_hash():
    evts = []
    for _ in range(3):
        req = _mk_req()
        res = _mk_res()
        evts.append(append_audit_event(PG_DSN, req, res))

    # Tamper with the second event's hash
    evts[1] = AuditEventV1(
        event_id=evts[1].event_id,
        request_id=evts[1].request_id,
        ts=evts[1].ts,
        actor=evts[1].actor,
        action=evts[1].action,
        decision=evts[1].decision,
        payload=evts[1].payload,
        prev_hash=evts[1].prev_hash,
        hash="0000000000000000000000000000000000000000000000000000000000000000",
    )

    ok, idx = verify_chain(evts)
    assert ok is False
    assert idx == 1  # broken at the tampered event


def test_verify_chain_detects_broken_prev_link():
    evts = []
    for _ in range(3):
        req = _mk_req()
        res = _mk_res()
        evts.append(append_audit_event(PG_DSN, req, res))

    # Break the chain link: overwrite prev_hash of event 2
    evts[2] = AuditEventV1(
        event_id=evts[2].event_id,
        request_id=evts[2].request_id,
        ts=evts[2].ts,
        actor=evts[2].actor,
        action=evts[2].action,
        decision=evts[2].decision,
        payload=evts[2].payload,
        prev_hash="WRONG",
        hash=evts[2].hash,
    )

    ok, idx = verify_chain(evts)
    assert ok is False
    assert idx == 2


# ── Integration: payload stored as JSONB, readable ───────


def test_payload_readable_from_db():
    req = _mk_req()
    res = _mk_res()
    evt = append_audit_event(PG_DSN, req, res)

    conn = psycopg2.connect(PG_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM audit_events WHERE event_id = %s::uuid;",
                (evt.event_id,),
            )
            row = cur.fetchone()
            assert row is not None
            import json

            payload = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            assert payload["request"]["tool"] == req.tool
            assert payload["response"]["decision"] == res.decision
    finally:
        conn.close()


# ── Integration: unique constraints enforced ─────────────


def test_duplicate_event_id_rejected():
    req = _mk_req()
    res = _mk_res()
    evt = append_audit_event(PG_DSN, req, res)

    # Try to insert a row with the same event_id manually
    conn = psycopg2.connect(PG_DSN)
    try:
        with conn.cursor() as cur, pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute(
                """
                    INSERT INTO audit_events
                      (request_id, event_id, ts, actor, action, decision,
                       payload, prev_hash, hash)
                    VALUES
                      (%s::uuid, %s::uuid, now(), 'x', 'x', 'x',
                       '{}'::jsonb, '', 'unique_hash_abc');
                    """,
                (str(uuid.uuid4()), evt.event_id),
            )
    finally:
        conn.close()
