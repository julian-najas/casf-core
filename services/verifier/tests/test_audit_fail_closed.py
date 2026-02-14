"""Regression tests: audit append is fail-closed.

These tests do not require a running Postgres instance. We patch
`append_audit_event` to simulate an outage and assert the verifier denies.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import patch

from helpers import get_client


def test_audit_append_failure_denies_fail_closed():
    overrides = {
        "PG_DSN": "dbname=casf user=casf password=casf host=localhost port=5432",
        "REDIS_URL": "redis://localhost:6379/0",
        "OPA_URL": "http://localhost:8181",
        "CASF_DISABLE_AUDIT": "0",
        "ANTI_REPLAY_ENABLED": "false",
    }
    saved = {k: os.environ.get(k) for k in overrides}
    os.environ.update(overrides)

    try:
        client, main_mod = get_client(anti_replay=False, disable_audit=False)

        payload = {
            "request_id": str(uuid.uuid4()),
            "tool": "cliniccloud.list_appointments",
            "mode": "READ_ONLY",
            "role": "receptionist",
            "subject": {"patient_id": "p1"},
            "args": {},
            "context": {"tenant_id": "t-demo"},
        }

        from src.verifier.opa_client import OpaDecision

        with (
            patch.object(
                main_mod.opa, "evaluate", return_value=OpaDecision(allow=True, violations=[])
            ),
            patch.object(main_mod, "append_audit_event", side_effect=Exception("pg down")),
        ):
            r = client.post("/verify", json=payload)
            assert r.status_code == 200
            body = r.json()
            assert body["decision"] == "DENY"
            assert "FAIL_CLOSED" in body["violations"]
            assert "Audit_Unavailable" in body["violations"]
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
