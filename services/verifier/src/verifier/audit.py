from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Tuple

import psycopg2

from .models import AuditEventV1, VerifyRequestV1, VerifyResponseV1

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _canonical_json(obj) -> str:
    # Stable canonicalization for hashing
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def _get_prev_hash(conn) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT hash_self FROM audit_events ORDER BY id DESC LIMIT 1;")
        row = cur.fetchone()
        return row[0] if row else ""

def append_audit_event(pg_dsn: str, req: VerifyRequestV1, res: VerifyResponseV1) -> AuditEventV1:
    """
    Append-only audit event with hash chain:
      hash_self = sha256(hash_prev + payload_json)
    """
    event_id = str(uuid.uuid4())
    ts = _utc_now_iso()

    payload = {
        "event_id": event_id,
        "timestamp": ts,
        "request": req.model_dump(),
        "response": res.model_dump(),
    }
    payload_json = _canonical_json(payload)

    conn = psycopg2.connect(pg_dsn)
    try:
        prev = _get_prev_hash(conn)
        h_self = _sha256_hex(prev + payload_json)

        evt = AuditEventV1(
            event_id=event_id,
            request_id=req.request_id,
            tool=req.tool,
            decision=res.decision,
            timestamp=ts,
            mode=req.mode,
            role=req.role,
            violations=res.violations,
            hash_prev=prev,
            hash_self=h_self,
            payload_json=payload_json,
        )

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_events
                  (event_id, request_id, tool, decision, hash_prev, hash_self, payload_json)
                VALUES
                  (%s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    evt.event_id,
                    evt.request_id,
                    evt.tool,
                    evt.decision,
                    evt.hash_prev,
                    evt.hash_self,
                    evt.payload_json,
                ),
            )
        conn.commit()
        return evt
    finally:
        conn.close()
