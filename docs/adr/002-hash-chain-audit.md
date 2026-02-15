# ADR-002: Hash-chained append-only audit trail

| Field    | Value                        |
|----------|------------------------------|
| Status   | Accepted                     |
| Date     | 2026-01-20                   |
| Authors  | Julian Najas                 |

## Context

Regulatory and forensic requirements demand that every verification decision
is recorded **immutably**.  If an attacker or bug silently modifies past
records, the tampering must be detectable.

## Decision

Each audit event (`AuditEventV1`) is stored in Postgres with:

| Column      | Type      | Purpose                              |
|-------------|-----------|--------------------------------------|
| `event_id`  | UUID      | Unique identifier                    |
| `request_id`| UUID      | Correlation with the originating call|
| `ts`        | TIMESTAMPTZ | UTC wall-clock                     |
| `actor`     | TEXT      | `role:<role>`                        |
| `action`    | TEXT      | Tool name                            |
| `decision`  | TEXT      | `ALLOW` or `DENY`                    |
| `payload`   | JSONB     | Full request + response              |
| `prev_hash` | TEXT      | SHA-256 hex of the previous event    |
| `hash`      | TEXT      | SHA-256 hex of the current event     |

### Hash computation

```
hash = SHA-256(request_id | event_id | ts | actor | action | decision | canonical(payload) | prev_hash)
```

The genesis event has `prev_hash = ""`.

### Verification

`verify_chain(events)` walks the list and recomputes each hash.  A mismatch
at index `i` means event `i` (or its predecessor) was tampered with.

## Consequences

- **Pros**: tamper-evidence without extra infrastructure (no blockchain
  needed), compatible with standard Postgres backup/replication, O(n)
  verification.
- **Cons**: single-writer assumption (concurrent appends must be
  serialised — current implementation uses `SELECT … FOR UPDATE`-style
  ordering via sequence); chain verification is linear and grows with table
  size (mitigated by periodic digest export via `export_audit_digest.py`).

## Alternatives considered

- **External ledger (QLDB, blockchain)**: rejected — adds vendor lock-in
  and latency; Postgres + hash chain gives equivalent tamper-evidence for
  our threat model.
- **Event sourcing without hash chain**: rejected — no tamper detection.
