# ADR-003: Fail-closed on infrastructure failures

| Field    | Value                        |
|----------|------------------------------|
| Status   | Accepted                     |
| Date     | 2026-02-01                   |
| Authors  | Julian Najas                 |

## Context

The verifier depends on three external systems at runtime:

| Dependency | Used for                      |
|------------|-------------------------------|
| Redis      | Anti-replay, SMS rate-limit   |
| OPA        | Policy evaluation             |
| Postgres   | Audit trail append            |

When any dependency is unavailable, the verifier must decide whether to
**fail open** (allow the action) or **fail closed** (deny the action).

## Decision

**All paths fail closed.**  Specifically:

| Failure              | Behaviour                                              | Metric label            |
|----------------------|--------------------------------------------------------|-------------------------|
| Redis unreachable    | Write tools → `DENY` + `FAIL_CLOSED`                  | `trigger="redis"`       |
| OPA unreachable      | All tools → `DENY` + `FAIL_CLOSED`                    | `trigger="opa"`         |
| OPA timeout          | All tools → `DENY` + `FAIL_CLOSED`                    | `trigger="opa"`         |
| Postgres audit fail  | Decision flips to `DENY` + `FAIL_CLOSED` + `Audit_Unavailable` | `trigger="postgres"` |

Each fail-closed event increments `casf_fail_closed_total{trigger=...}` so
operators can alert on infrastructure degradation before it blocks all traffic.

## Consequences

- **Pros**: no data leak on infra failure; operators have clear metrics to
  detect and remediate.
- **Cons**: total Redis or OPA outage = total service denial; requires
  robust monitoring and alerting on `casf_fail_closed_total`.

## Alternatives considered

- **Fail open for reads**: considered — reads are safe, writes are not.
  Rejected for v1 to keep the security posture uniform; may revisit in v2
  with per-mode fail-open for `READ_ONLY` operations.
- **Circuit breaker with cached decisions**: deferred to future version.
