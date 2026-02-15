from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import psycopg2
import psycopg2.extras

from .models import AuditEventV1, VerifyRequestV1, VerifyResponseV1

__all__ = ["append_audit_event", "compute_hash", "verify_chain"]

psycopg2.extras.register_uuid()  # type: ignore[no-untyped-call]

# ── Helpers ──────────────────────────────────────────────


def _utc_now_iso() -> str:
    """ISO-8601 UTC timestamp, always with 'Z' suffix (no +00:00 ambiguity)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _canonical_json(obj: object) -> str:
    """Stable JSON: sorted keys, compact separators, UTF-8."""

    def _default(o: object) -> str:
        if isinstance(o, uuid.UUID):
            return str(o)
        if isinstance(o, datetime):
            # Prefer a stable ISO string; UTC becomes 'Z' where possible.
            s = o.isoformat()
            return s.replace("+00:00", "Z")
        return str(o)

    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_default,
    )


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ── Hash contract ────────────────────────────────────────


def compute_hash(
    request_id: str | uuid.UUID,
    event_id: str | uuid.UUID,
    ts: str,
    actor: str,
    action: str,
    decision: str,
    payload: dict[str, Any],
    prev_hash: str,
) -> str:
    """
    Deterministic hash contract (rigid, ordered):
        sha256(request_id + event_id + ts + actor + action + decision
               + canonical_json(payload) + prev_hash)
    All fields concatenated as plain strings.  prev_hash is "" for genesis.
    """
    parts = (
        str(request_id),
        str(event_id),
        str(ts),
        str(actor),
        str(action),
        str(decision),
        _canonical_json(payload),
        str(prev_hash),
    )
    return _sha256_hex("".join(parts))


def verify_chain(events: list[AuditEventV1]) -> tuple[bool, int | None]:
    """
    Walk a list of events (ordered by id ASC) and verify the hash chain.
    Returns (True, None) if valid, or (False, broken_index).
    """
    for i, evt in enumerate(events):
        expected_prev = events[i - 1].hash if i > 0 else ""
        if evt.prev_hash != expected_prev:
            return False, i
        expected_hash = compute_hash(
            request_id=evt.request_id,
            event_id=evt.event_id,
            ts=evt.ts,
            actor=evt.actor,
            action=evt.action,
            decision=evt.decision,
            payload=evt.payload,
            prev_hash=evt.prev_hash,
        )
        if evt.hash != expected_hash:
            return False, i
    return True, None


# ── Persistence ──────────────────────────────────────────


def _get_prev_hash(conn: psycopg2.extensions.connection) -> str:
    """Fetch the hash of the last event (inside the same transaction / lock)."""
    with conn.cursor() as cur:
        cur.execute("SELECT hash FROM audit_events ORDER BY id DESC LIMIT 1;")
        row = cur.fetchone()
        return row[0] if row else ""


def append_audit_event(
    pg_dsn: str,
    req: VerifyRequestV1,
    res: VerifyResponseV1,
    *,
    action_override: str | None = None,
) -> AuditEventV1:
    """
    Append-only audit event with hash chain.
    Uses a Postgres advisory lock to serialise writers and guarantee
    prev_hash consistency under concurrency.

    action_override: if set, replaces the default action (req.tool) — used for
    REPLAY_DETECTED events.
    """
    event_id = uuid.uuid4()
    ts = _utc_now_iso()
    actor = f"role:{req.role}"
    action = action_override or req.tool

    payload = {
        "request": req.model_dump(mode="json"),
        "response": res.model_dump(mode="json"),
    }

    conn = psycopg2.connect(pg_dsn)
    try:
        conn.autocommit = False

        with conn.cursor() as cur:
            # Advisory lock (xact-scoped, key = fixed int 42).
            # Serialises all audit writers; released on COMMIT/ROLLBACK.
            cur.execute("SELECT pg_advisory_xact_lock(42);")

        prev_hash = _get_prev_hash(conn)
        h = compute_hash(
            request_id=req.request_id,
            event_id=event_id,
            ts=ts,
            actor=actor,
            action=action,
            decision=res.decision,
            payload=payload,
            prev_hash=prev_hash,
        )

        evt = AuditEventV1(
            event_id=event_id,
            request_id=req.request_id,
            ts=ts,
            actor=actor,
            action=action,
            decision=res.decision,
            payload=payload,
            prev_hash=prev_hash,
            hash=h,
        )

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_events
                  (request_id, event_id, ts, actor, action, decision,
                   payload, prev_hash, hash)
                VALUES
                  (%s::uuid, %s::uuid, %s, %s, %s, %s,
                   %s::jsonb, %s, %s);
                """,
                (
                    str(evt.request_id),
                    str(evt.event_id),
                    evt.ts,
                    evt.actor,
                    evt.action,
                    evt.decision,
                    _canonical_json(evt.payload),
                    evt.prev_hash,  # "" for genesis (matches contract & compute_hash)
                    evt.hash,
                ),
            )
        conn.commit()
        return evt
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
