# Operator Guide — CASF Verifier

> Everything you need to run CASF-core in production without asking the author.

---

## 1. Architecture at a glance

```
              ┌──────────┐
  Client ───▶│ Verifier  │──▶ OPA (policy)
              │ :8000     │──▶ Redis (rate-limit + anti-replay)
              │ (FastAPI) │──▶ Postgres (audit trail)
              └──────────┘
```

**Verifier** is the only externally-exposed component.
OPA, Redis, and Postgres are internal dependencies — never expose them.

---

## 2. Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PG_DSN` | **yes** | — | Postgres DSN. Example: `dbname=casf user=casf password=SECRET host=pg port=5432` |
| `REDIS_URL` | no | `redis://redis:6379/0` | Redis connection string |
| `OPA_URL` | no | `http://opa:8181` | OPA base URL (no trailing slash) |
| `ANTI_REPLAY_ENABLED` | no | `true` | Enable idempotent anti-replay gate (`true`, `1`, `yes`) |
| `ANTI_REPLAY_TTL_SECONDS` | no | `86400` | TTL for replay keys in Redis (seconds) |
| `CASF_DISABLE_AUDIT` | no | — | Set to `1` to skip audit writes (tests only — **never in prod**) |

### Postgres schema

The database must be initialised with [deploy/sql/init.sql](../deploy/sql/init.sql) before first start.
The table `audit_events` is append-only; never `DELETE` or `TRUNCATE` in prod.

---

## 3. Deployment

### Docker Compose (reference)

```bash
cd deploy/compose
docker compose up -d
```

This starts all four services (postgres, redis, opa, verifier) with healthchecks.
The Verifier is exposed on **host port 8088 → container 8000**.

### Standalone container

```bash
docker build -t casf-verifier services/verifier/
docker run -d \
  -e PG_DSN="dbname=casf user=casf password=SECRET host=pg.internal port=5432" \
  -e REDIS_URL="redis://redis.internal:6379/0" \
  -e OPA_URL="http://opa.internal:8181" \
  -p 8000:8000 \
  casf-verifier
```

The image runs **`uvicorn verifier.main:app --host 0.0.0.0 --port 8000`** (single-worker).
For production, set `WEB_CONCURRENCY` or front with gunicorn:

```bash
CMD ["gunicorn", "verifier.main:app", "-k", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", "--bind", "0.0.0.0:8000"]
```

---

## 4. Healthchecks

| Endpoint | Purpose | Returns |
|----------|---------|---------|
| `GET /health` | **Liveness** — process alive | `200 {"status": "ok"}` always |
| `GET /healthz` | **Readiness** — all deps reachable | `200` or `503` with failing component |

`/healthz` checks Postgres (SELECT 1), Redis (PING), and OPA (policy eval) sequentially.
Each check has a **2-second timeout**. If any fails → 503 with `detail: "<component>: <error>"`.

**Kubernetes probes (recommended):**

```yaml
livenessProbe:
  httpGet: { path: /health, port: 8000 }
  periodSeconds: 10
readinessProbe:
  httpGet: { path: /healthz, port: 8000 }
  periodSeconds: 15
  failureThreshold: 3
```

---

## 5. Metrics & monitoring

### Scraping

`GET /metrics` returns Prometheus text exposition format.

```yaml
# prometheus.yml
scrape_configs:
  - job_name: casf-verifier
    metrics_path: /metrics
    static_configs:
      - targets: ["verifier:8000"]
    scrape_interval: 15s
```

### Key metrics

| Metric | What to watch |
|--------|---------------|
| `casf_verify_total` | Overall traffic volume |
| `casf_verify_decision_total{decision="DENY"}` | Deny rate — spike = incident or policy change |
| `casf_verify_duration_seconds` | p95 latency via `histogram_quantile(0.95, ...)` |
| `casf_verify_in_flight` | Concurrent requests — detect overload |
| `casf_fail_closed_total{trigger}` | **Alert on any increment** — infrastructure failure |
| `casf_opa_error_total{kind}` | OPA health by error type |
| `casf_replay_hit_total` | Normal idempotent returns (informational) |
| `casf_replay_mismatch_total` | **Alert** — potential tampering or client bug |

### Grafana dashboard (minimal)

| Panel | PromQL |
|-------|--------|
| Request rate | `rate(casf_verify_total[5m])` |
| Deny rate | `rate(casf_verify_decision_total{decision="DENY"}[5m])` |
| p50 latency | `histogram_quantile(0.50, rate(casf_verify_duration_seconds_bucket[5m]))` |
| p95 latency | `histogram_quantile(0.95, rate(casf_verify_duration_seconds_bucket[5m]))` |
| p99 latency | `histogram_quantile(0.99, rate(casf_verify_duration_seconds_bucket[5m]))` |
| In-flight | `casf_verify_in_flight` |
| Fail-closed (by trigger) | `increase(casf_fail_closed_total[5m])` |
| OPA errors (by kind) | `increase(casf_opa_error_total[5m])` |

### Alerts (recommended)

```yaml
groups:
  - name: casf
    rules:
      - alert: CASFFailClosed
        expr: increase(casf_fail_closed_total[5m]) > 0
        for: 0m
        labels: { severity: critical }
        annotations:
          summary: "CASF fail-closed triggered ({{ $labels.trigger }})"
      - alert: CASFReplayMismatch
        expr: increase(casf_replay_mismatch_total[5m]) > 0
        for: 0m
        labels: { severity: warning }
        annotations:
          summary: "Replay mismatch detected — possible tampering"
      - alert: CASFP95High
        expr: histogram_quantile(0.95, rate(casf_verify_duration_seconds_bucket[5m])) > 0.5
        for: 5m
        labels: { severity: warning }
        annotations:
          summary: "CASF p95 latency above 500ms"
```

Full cardinality rules → [docs/observability.md](observability.md).

---

## 6. Failure modes

CASF follows **fail-closed for writes, fail-open for reads** (v1 pragmatic).

### Redis down

| Scenario | Behaviour |
|----------|-----------|
| Write tool (`create_appointment`, `cancel_appointment`, `send_sms`, `generate_invoice`) | **DENY** with `FAIL_CLOSED` + `Inv_ReplayCheckUnavailable` |
| Read tool (`list_appointments`, `summary_history`) | Skip anti-replay, proceed normally |
| SMS rate-limit check fails | **DENY** with `FAIL_CLOSED` + `Inv_NoSmsBurst` |
| **Metric** | `casf_fail_closed_total{trigger="redis"}` increments |

**Recovery:** Redis restart is normally instant.  Anti-replay keys are ephemeral (TTL = 24h default).
No data loss on Redis restart — worst case: duplicate processing of in-flight requests.

### OPA down

| Scenario | Behaviour |
|----------|-----------|
| Write tool | **DENY** with `FAIL_CLOSED` + `OPA_Unavailable` |
| Read tool | Skip OPA, allow (rules-only) |
| **Metric** | `casf_opa_error_total{kind}` + `casf_fail_closed_total{trigger="opa"}` |

OPA error kinds and meaning:

| `kind` | Cause | Typical fix |
|--------|-------|-------------|
| `timeout` | OPA didn't respond in 350ms | Check OPA CPU/memory, increase `timeout_s` |
| `unavailable` | TCP connection refused / DNS failure | OPA container down or network partition |
| `bad_status` | OPA returned HTTP ≥ 400 | Bad policy bundle, check OPA logs |
| `bad_response` | OPA returned non-JSON | OPA misconfiguration or proxy interference |

**Recovery:** Fix OPA and verify with `/healthz`. All writes will resume automatically.

### Postgres down

| Scenario | Behaviour |
|----------|-----------|
| Audit append fails | Response still returns to client, but `reason` gets `| audit_append_failed` suffix |
| Chain broken | `export_audit_digest.py` will report `chain_valid: false` |
| `/healthz` | Returns `503` immediately |
| **Impact** | Decisions still work — only audit logging degrades |

**Recovery:** Fix Postgres.  Run `export_audit_digest.py` to verify chain continuity.
If chain is broken, investigate the gap — events are append-only, so no automatic healing.

### Connection timeouts (reference)

| Component | Timeout | Where set |
|-----------|---------|-----------|
| Redis (rate-limit, anti-replay) | 200ms | `RateLimiter.__init__` (`timeout_s=0.2`) |
| OPA (policy eval) | 350ms | `OpaClient.__init__` (`timeout_s=0.35`) |
| Healthcheck (each dep) | 2s | `healthz()` handler |

---

## 7. Anti-replay / idempotency

When `ANTI_REPLAY_ENABLED=true` (default):

1. Every `/verify` request is keyed by `request_id`.
2. Payload fingerprint = SHA-256 of the canonical body (excluding `request_id`).
3. **New request** → claim key in Redis (atomic Lua SET NX EX), process normally.
4. **Replay, same payload** → return cached decision (no re-processing, no double audit).
5. **Replay, different payload** → hard DENY (`Inv_ReplayPayloadMismatch`).
6. **Concurrent (pending)** → DENY (`Inv_ReplayConcurrent`).

Keys expire after `ANTI_REPLAY_TTL_SECONDS` (default 24h).

**Operational note:** If you need to reprocess a request, you must either:
- Wait for TTL expiry, or
- Manually `DEL casf:req:<request_id>` from Redis.

---

## 8. Audit chain

### How it works

Every `/verify` decision is appended to `audit_events` in Postgres with a SHA-256 hash chain:

```
hash(N) = SHA-256(request_id + event_id + ts + actor + action + decision
                  + canonical_json(payload) + hash(N-1))
```

The first event uses `prev_hash = ""` (genesis). Writers are serialised via
`pg_advisory_xact_lock(42)` to guarantee chain consistency.

### Verifying the chain

```bash
# From inside the container or with PG_DSN set:
python -m verifier.export_audit_digest           # yesterday
python -m verifier.export_audit_digest 2026-02-09  # specific date
```

Output:
```json
{
  "generated_at": "2026-02-10T08:00:00.000000+00:00",
  "window": "2026-02-09",
  "event_count": 142,
  "first_hash": "a1b2c3...",
  "last_hash": "d4e5f6...",
  "chain_valid": true,
  "digest_hash": "7890ab..."
}
```

Exit code: `0` = valid, `1` = broken chain, `2` = connectivity error.

### Anchoring to external storage

Save the daily digest to tamper-evident storage:

```bash
# Option A: GPG sign
python -m verifier.export_audit_digest | gpg --clearsign > digest_$(date +%F).asc

# Option B: AWS S3 Object Lock (WORM)
python -m verifier.export_audit_digest > /tmp/digest.json
aws s3 cp /tmp/digest.json s3://casf-audit-worm/$(date +%F).json \
  --object-lock-mode COMPLIANCE --object-lock-retain-until-date $(date -d "+7 years" +%FT%TZ)

# Option C: append to SIEM
python -m verifier.export_audit_digest | curl -X POST https://siem.internal/ingest -d @-
```

---

## 9. Runbooks

### RB-1: Fail-closed alerts firing

**Symptom:** `CASFFailClosed` alert, `casf_fail_closed_total` incrementing.

1. Check `trigger` label → identifies which dependency failed (`redis` / `opa` / `rules`).
2. Run `curl http://verifier:8000/healthz` → will return 503 with the failing component.
3. Fix the failing dependency (see Failure Modes above).
4. Verify with `/healthz` → 200 means all clear.
5. **Impact:** Write operations were denied during the outage. Read operations continued (fail-open).
   No manual intervention needed after dependency recovery.

### RB-2: OPA down / errors

**Symptom:** `casf_opa_error_total` incrementing, writes denied.

1. Check `kind` label: `timeout` → performance issue; `unavailable` → container down.
2. `docker logs opa` (or equivalent) → check for policy compilation errors.
3. Verify OPA health: `curl http://opa:8181/health`.
4. Test policy eval: `curl -X POST http://opa:8181/v1/data/casf -d '{"input":{"tool":"healthcheck"}}'`.
5. Once OPA responds → `/healthz` returns 200 → writes resume.

### RB-3: Replay mismatch detected

**Symptom:** `casf_replay_mismatch_total` incrementing.

1. This means a client sent the same `request_id` with a different payload.
2. Check client logs — likely a bug (request_id reuse), or a possible tampering attempt.
3. The request was denied. No action needed on the server side.
4. If this is a legitimate retry with modified payload, the client must generate a new `request_id`.

### RB-4: Audit chain broken

**Symptom:** `export_audit_digest` returns `chain_valid: false`, exit code 1.

1. Run with the specific date: `python -m verifier.export_audit_digest 2026-02-09`.
2. Query the gap: `SELECT id, ts, prev_hash, hash FROM audit_events ORDER BY id;`
3. Identify the broken link — typically caused by Postgres failure during write.
4. **This is not self-healing.** Document the gap and include it in the audit report.
5. All new events after the gap will form a valid chain from the last successful event.

### RB-5: High latency (p95 > 500ms)

**Symptom:** `CASFP95High` alert.

1. Check `casf_verify_in_flight` — high value = overload, scale horizontally.
2. Check `casf_opa_error_total{kind="timeout"}` — OPA slow = tune OPA resources.
3. Check Postgres query times (audit writes under advisory lock contention).
4. Review Redis latency (`redis-cli --latency`).
5. If OPA is the bottleneck: increase `OpaClient.timeout_s` (currently 350ms) or add OPA replicas.

---

## 10. Quick reference

```text
POST /verify        → Main decision endpoint
GET  /health        → Liveness (always 200)
GET  /healthz       → Readiness (200 or 503)
GET  /metrics       → Prometheus metrics

Tools (write):  create_appointment, cancel_appointment, send_sms, generate_invoice
Tools (read):   list_appointments, summary_history

Modes:  ALLOW | STEP_UP | READ_ONLY | KILL_SWITCH
Roles:  receptionist | nurse | doctor | billing | custodian | system
```
