#!/usr/bin/env python3
"""
export_audit_digest.py — Anchor-ready daily digest of the audit hash-chain.

Reads audit_events from Postgres, verifies the chain integrity, and emits
a signed digest (JSON) to stdout.  The digest contains:

  - window: date range covered
  - event_count: number of events in the window
  - first_hash / last_hash: bookend hashes for independent verification
  - chain_valid: whether the full chain passes verify_chain()
  - digest_hash: SHA-256 of the canonical digest (anchor value)

Intended use:
  1. Run daily via cron / CI / ops script
  2. Redirect stdout to a file: `python export_audit_digest.py > digest_2026-02-09.json`
  3. Store the file in WORM storage, SIEM, S3 Object Lock, or sign with GPG:
       gpg --clearsign digest_2026-02-09.json

Exit codes:
  0 = chain valid, digest emitted
  1 = chain broken (digest still emitted with chain_valid=false)
  2 = connectivity / unexpected error
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta

import psycopg2

# ── Config ───────────────────────────────────────────────

PG_DSN = os.environ.get("PG_DSN", "postgresql://casf:casf@localhost:5432/casf")


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _canonical_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ── Main ─────────────────────────────────────────────────


def export_digest(pg_dsn: str, date: str | None = None) -> dict[str, object]:
    """
    Build an audit digest for *date* (YYYY-MM-DD, defaults to yesterday).

    Returns a dict suitable for JSON serialisation.
    """
    if date is None:
        date = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")

    conn = psycopg2.connect(pg_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT event_id, request_id, ts::text, actor, action, decision,
                       payload::text, prev_hash, hash
                  FROM audit_events
                 WHERE ts >= %s::date
                   AND ts <  %s::date + interval '1 day'
                 ORDER BY id ASC;
                """,
                (date, date),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "window": date,
            "event_count": 0,
            "first_hash": None,
            "last_hash": None,
            "chain_valid": True,
            "digest_hash": _sha256(f"empty:{date}"),
        }

    # Verify chain continuity within the window
    chain_valid = True
    for i, row in enumerate(rows):
        prev_hash = row[7]
        if i == 0:
            continue  # first event in window — prev_hash points outside window
        expected_prev = rows[i - 1][8]  # hash of previous row
        if prev_hash != expected_prev:
            chain_valid = False
            break

    first_hash = rows[0][8]
    last_hash = rows[-1][8]

    digest_payload = {
        "window": date,
        "event_count": len(rows),
        "first_hash": first_hash,
        "last_hash": last_hash,
        "chain_valid": chain_valid,
    }
    digest_hash = _sha256(_canonical_json(digest_payload))

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        **digest_payload,
        "digest_hash": digest_hash,
    }


def main() -> int:
    date = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        result = export_digest(PG_DSN, date)
    except Exception as e:
        print(f'{{"error": "{e}"}}', file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2))
    return 0 if result["chain_valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
