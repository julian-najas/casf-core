# Operability — CASF Verifier

## Startup

```bash
# From repo root
make up          # docker compose up --build -d
make ps          # verify all services are healthy
```

Expected healthy state: `postgres`, `redis`, `opa`, `verifier` — all `healthy`.

## Health endpoints

| Endpoint | Type | Behaviour |
|----------|------|-----------|
| `GET /health` | Liveness | Returns `200` if the process is alive. No dependency checks. |
| `GET /healthz` | Readiness | Returns `200` only when Postgres, Redis, AND OPA are reachable. Returns `503` with detail on first failure. |

### Kubernetes probes (example)

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /healthz
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 5
  failureThreshold: 3
```

## Failure modes

| Component down | Effect on writes | Effect on reads |
|---------------|-----------------|-----------------|
| **Redis** | DENY (fail-closed) | Pass-through (no rate limit / replay check) |
| **OPA** | DENY (fail-closed) | ALLOW (fail-open, logged) |
| **Postgres** | DENY (fail-closed) | DENY (no audit = no decision) |
| **All healthy** | Normal operation | Normal operation |

**Invariant:** No write decision is issued without all dependencies healthy.

## Restart / recovery

- **Verifier crash:** Container restarts automatically (`docker compose`). Stateless — no warm-up needed.
- **Redis restart:** Rate limit counters reset. Anti-replay window resets. Accept as transient.
- **Postgres restart:** Audit chain continues from last committed event (`prev_hash` query). No gap.
- **OPA restart:** Policies loaded from volume mount on startup. No state.

## Scaling

- Verifier is **stateless** — can be scaled horizontally behind a load balancer.
- Redis is a **single writer** — use Redis Sentinel or Cluster for HA.
- Postgres audit table is **append-only** — can be replicated read-only.
- OPA is **stateless** — scale horizontally; bundle server recommended for production.

## Log inspection

```bash
make logs                    # tail all services
docker compose -f deploy/compose/docker-compose.yml logs verifier -f --tail=100
```

Logs are structured JSON (see below). Filter with `jq`:

```bash
docker compose logs verifier --no-log-prefix | jq 'select(.decision == "DENY")'
```

## Runbook: common issues

### 1. Verifier returns 503 on `/healthz`

**Cause:** One or more dependencies unreachable.
**Action:** Check `detail` field in response. Verify the failing service is running:

```bash
docker compose ps
docker compose logs <service> --tail=20
```

### 2. All writes return DENY

**Cause:** Redis or OPA down → fail-closed.
**Action:** Check Redis (`redis-cli ping`) and OPA (`curl http://localhost:8181/health`).

### 3. Audit chain broken

**Cause:** Manual DB edit or concurrent writer without advisory lock.
**Action:** Run the digest verifier:

```bash
python -m verifier.export_audit_digest <date>
```

Check `chain_valid` field. If `false`, investigate the `broken_at` index.

### 4. Rate limit not resetting

**Cause:** Redis key TTL not expiring (clock skew or persistence issue).
**Action:** Inspect key:

```bash
redis-cli TTL sms:<patient_id>
redis-cli GET sms:<patient_id>
```

## Backup & restore

- **Postgres:** Standard `pg_dump` / `pg_restore`. Audit table is append-only — no UPDATE/DELETE.
- **Redis:** Ephemeral by design. Loss = reset of rate limit windows and replay cache. Acceptable.

## Monitoring

See [observability.md](observability.md) for the full metrics catalogue.

Key alerts to configure:

| Alert | Condition | Severity |
|-------|-----------|----------|
| Verifier down | `/healthz` returns non-200 for > 30s | Critical |
| High deny rate | `rate(casf_verify_decision_total{decision="DENY"}[5m]) > 0.5` | Warning |
| Fail-closed spike | `rate(casf_fail_closed_total[5m]) > 0` | Critical |
| OPA errors | `rate(casf_opa_error_total[5m]) > 0.1` | Warning |
| Audit latency | `histogram_quantile(0.99, casf_verify_duration_seconds) > 1.0` | Warning |
