# Observability — CASF Verifier

## Endpoint

`GET /metrics` — Prometheus text exposition format (`text/plain; version=0.0.4`).

## Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `casf_verify_total` | counter | — | Total `/verify` requests received |
| `casf_verify_decision_total` | counter | `decision` ∈ {`ALLOW`, `DENY`} | Decisions by outcome |
| `casf_verify_duration_seconds` | histogram | — | Latency of `/verify` requests |
| `casf_verify_in_flight` | gauge | — | Requests currently being processed |
| `casf_replay_hit_total` | counter | — | Anti-replay cache hits (idempotent returns) |
| `casf_replay_mismatch_total` | counter | — | Payload fingerprint mismatches |
| `casf_replay_concurrent_total` | counter | — | Concurrent / pending denials |
| `casf_fail_closed_total` | counter | `trigger` ∈ {`redis`, `opa`, `rules`, `postgres`} | Fail-closed denials by trigger |
| `casf_rate_limit_deny_total` | counter | — | SMS rate-limit denials |
| `casf_opa_error_total` | counter | `kind` ∈ {`timeout`, `unavailable`, `bad_status`, `bad_response`} | OPA evaluation errors |

## Cardinality rules

> **Do NOT add high-cardinality labels.** The following are **forbidden** as metric labels:
>
> `tenant_id`, `patient_id`, `request_id`, `tool`, `role`, `user_id`, `session_id`
>
> These create unbounded time series and will break Prometheus/Grafana at scale.

If you need per-tool or per-tenant visibility, use **structured logs** or **exemplars**, not labels.

## Allowed label values

Every label must have a **bounded, predefined** set of values:

- `decision`: `ALLOW` | `DENY` (2 values)
- `trigger`: `redis` | `opa` | `rules` | `postgres` (4 values)
- `kind`: `timeout` | `unavailable` | `bad_status` | `bad_response` (4 values)

**Max cardinality per metric: ≤ 4 series.** Any PR adding a label must document the bounded value set here.

## Design

- Zero external dependencies (no `prometheus_client`)
- Thread-safe `threading.Lock` registry in `src/verifier/metrics.py`
- Histogram buckets: `0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5` seconds
- Counters at every decision return point — no double-counting
