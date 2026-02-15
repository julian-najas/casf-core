# ADR-001: Deny-by-default verification model

| Field    | Value                        |
|----------|------------------------------|
| Status   | Accepted                     |
| Date     | 2026-01-15                   |
| Authors  | Julian Najas                 |

## Context

CASF acts as a zero-trust gateway between AI agents and external tools that
handle PHI/PII (clinical records, SMS, billing).  Any tool invocation that is
**not explicitly authorised** must be blocked — a single false-positive is
preferable to a single leak.

## Decision

The verifier applies a **deny-by-default** pipeline:

1. **Hard invariants** (`rules.py`) — enforced locally, no network call:
   - `patient_id` required on every request.
   - Write tools blocked under `READ_ONLY` / `KILL_SWITCH` modes.
   - SMS rate-limited per patient per hour (fail-closed on Redis failure).

2. **OPA policy evaluation** — Rego rules loaded from `policies/casf.rego`.
   If OPA is unreachable the decision is `DENY` with `FAIL_CLOSED`.

3. **Audit append** — every decision is hash-chained to Postgres.
   If audit write fails, the decision flips to `DENY` (fail-closed).

At no point in the pipeline does an unhandled path result in `ALLOW`.

## Consequences

- **Pros**: regulation-safe posture (GDPR, HIPAA-adjacent), auditable,
  new tools start denied until policy is written.
- **Cons**: new tools require an OPA rule before they can be used;
  operators must monitor `casf_fail_closed_total` to detect infra outages
  that silently deny all traffic.

## Alternatives considered

- **Allow-by-default with deny-list**: rejected — one missing rule leaks data.
- **Client-side guardrails only**: rejected — agents can be jailbroken.
