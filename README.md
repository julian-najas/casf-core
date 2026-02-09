# casf-core

CASF-core is a Zero-Trust Verification Service for PHI/PII automation.
It validates intent (tool/role/mode) before any execution and writes an append-only audit trail.

## Quickstart
docker compose -f deploy/compose/docker-compose.yml up --build

## Endpoint
POST http://localhost:8000/verify

## Rate limiting (Redis)

CASF-core aplica rate limit atómico (Redis Lua + TTL) para herramientas de escritura.

- Regla v1: `twilio.send_sms` → máximo 1 SMS por `subject.patient_id` cada 3600s.
- Si Redis no está disponible: **FAIL-CLOSED** para `twilio.send_sms` (`DENY` + `FAIL_CLOSED`).
- Otras herramientas no dependen de Redis en v1.

## Run locally

Requirements:
- Docker
- Docker Compose

Start the stack:
```bash
docker compose up -d
```

Verify:

* Verifier health: `http://localhost:8088/health`
* OPA: `http://localhost:8181/v1/data/casf`

Stop:

```bash
docker compose down
```

## Guarantees / Non-goals

### Guarantees
- Deny-by-default policy enforcement
- Fail-closed on write operations when dependencies (OPA, Redis, Postgres) are unavailable
- SMS rate limiting: max 1 message per patient_id per 1 hour
- Append-only audit log with hash chaining

### Non-goals
- No automatic retries or self-healing
- No policy latching
- No business-level authorization logic
- No SLA or high-availability guarantees

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
