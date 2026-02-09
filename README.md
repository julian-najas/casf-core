# casf-core

[![CI](https://github.com/<OWNER>/casf-core/actions/workflows/ci.yml/badge.svg)](https://github.com/<OWNER>/casf-core/actions/workflows/ci.yml)

Zero-trust verification gateway for PHI/PII automation.
Validates intent (tool / role / mode) before any execution, enforces policy via OPA, applies rate limiting, and writes an append-only hash-chained audit trail.

## Architecture

```
  request ──► Verifier ──► OPA (Rego)
                │
        ┌───────┼───────┐
      Redis   Postgres  Audit
    (rate-limit) (DDL)  (hash-chain)
```

| Component | Purpose |
|-----------|---------|
| **Verifier** (FastAPI) | Hard invariants, rate limiting, OPA consultation, audit |
| **OPA** (Rego) | External policy engine — deny-by-default governance |
| **Redis** | Atomic rate limiting (Lua + TTL), fail-closed on writes |
| **Postgres** | Append-only audit trail with SHA-256 hash chain |

## Quick start

```bash
# Start the full stack
docker compose -f deploy/compose/docker-compose.yml up --build -d

# Verify all services are healthy
docker compose -f deploy/compose/docker-compose.yml ps

# Run tests (from services/verifier with Python 3.11 venv)
cd services/verifier
pip install -e ".[dev]"
pytest -v

# Run OPA policy tests
docker run --rm -v "$PWD/policies:/policies:ro" \
  openpolicyagent/opa:0.63.0 test /policies -v

# Smoke test (PowerShell)
.\deploy\compose\scripts\smoke_pr3.ps1
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/verify` | Decision endpoint — validates and returns ALLOW / DENY / NEEDS_APPROVAL |
| `GET` | `/health` | Liveness probe (process alive) |
| `GET` | `/healthz` | Readiness probe (Postgres + Redis + OPA reachable) |

Verifier listens on port **8000** (container) → **8088** (host).

## Rate limiting

- `twilio.send_sms` → max **1 SMS per `patient_id` per hour** (Redis Lua atomic)
- Redis unavailable → **FAIL_CLOSED** (DENY for all writes)
- Other tools are not rate-limited in v1

## Guarantees

- Deny-by-default policy enforcement (OPA)
- Fail-closed on write operations when dependencies are unavailable
- Append-only audit log with SHA-256 hash chain (tamper-evident)
- Advisory lock serialisation for concurrent audit writes
- Semantic healthchecks (Postgres SELECT 1, Redis PING, OPA policy eval)

## Non-goals

- No automatic retries or self-healing
- No policy latching
- No business-level authorization logic
- No SLA or high-availability guarantees

## Project structure

```
contracts/          # JSON schemas + enum definitions (versioned, external)
policies/           # OPA Rego policies (single source of truth)
services/verifier/  # Python FastAPI service
deploy/compose/     # Docker Compose stack + smoke scripts
deploy/sql/         # Postgres DDL (init.sql)
```

## Release status

**CASF-core is scope-frozen.**

This repository is considered feature-complete for its intended role as a
zero-trust execution gateway.

No new features will be accepted. Only:
- critical bug fixes
- security patches
- documentation corrections

Any extension (modes latching, alerting, reporting, orchestration)
belongs to a separate project or layer.

## License

[Apache-2.0](LICENSE)
