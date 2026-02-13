# Architecture — CASF Verifier

## Overview

CASF-core is a **zero-trust verification gateway** for PHI/PII automation.
Every tool invocation passes through the Verifier before execution.
The system enforces policy, rate limiting, anti-replay, and audit in a single
synchronous request path.

## Component diagram

```
                  ┌─────────────────────────────────────────┐
                  │              Verifier (FastAPI)          │
  POST /verify ──►│                                         │
                  │  ┌──────────┐  ┌──────────┐  ┌───────┐ │
                  │  │Anti-Replay│  │  Rules   │  │  OPA  │ │
                  │  │  (Redis)  │  │  (v0/v1) │  │Client │ │
                  │  └─────┬────┘  └────┬─────┘  └───┬───┘ │
                  │        │            │             │     │
                  │  ┌─────▼────────────▼─────────────▼───┐ │
                  │  │           Audit (PG hash-chain)     │ │
                  │  └────────────────────────────────────┘ │
                  └─────────────────────────────────────────┘
                       │              │              │
                  ┌────▼───┐   ┌─────▼────┐   ┌────▼────┐
                  │ Redis  │   │ Postgres │   │   OPA   │
                  │(6379)  │   │ (5432)   │   │ (8181)  │
                  └────────┘   └──────────┘   └─────────┘
```

## Request flow

1. **Anti-replay gate** — `request_id` checked in Redis (`SET NX EX`).
   Same ID + same payload → cached decision. Same ID + different payload → DENY.
   Redis failure → **FAIL_CLOSED** on writes, pass-through on reads.

2. **Deterministic rules** (`rules.py`) — Hard invariants evaluated in-process:
   - No writes in `READ_ONLY` / `KILL_SWITCH` modes
   - SMS rate limit (1 per patient per hour via Redis Lua)
   - `patient_id` required on every request

3. **OPA policy evaluation** — External policy engine with deny-by-default.
   Evaluates `tool × mode × role` combinations against Rego policies.
   OPA failure → **FAIL_CLOSED** on writes, fail-open on reads.

4. **Audit append** — Every decision (ALLOW/DENY) is written to Postgres
   as an append-only hash-chained event. Advisory lock serialises writers.
   Audit failure → **FAIL_CLOSED** (no decision without audit record).

5. **Decision cache** — Final decision stored in Redis for anti-replay
   idempotency (24 h TTL).

## Key design decisions

| Decision | Rationale |
|----------|-----------|
| **Deny-by-default** | OPA policies deny unless explicitly allowed |
| **Fail-closed on writes** | Protecting PHI/PII is more important than availability for mutations |
| **Fail-open on reads** | Reads are safe to degrade; availability over consistency |
| **In-process rules + external OPA** | Hard invariants can't depend on network; soft policy is externalised |
| **Hash-chained audit** | Tamper-evident trail without external blockchain dependency |
| **Advisory lock (PG)** | Serialises audit writes; simpler than SERIALIZABLE isolation |
| **Zero-dep metrics** | No `prometheus_client`; minimal attack surface |

## Data flow

```
VerifyRequestV1 → Anti-Replay → Rules → OPA → Audit → VerifyResponseV1
                  (Redis)        (mem)   (HTTP)  (PG)
```

## Module map

| Module | Responsibility |
|--------|---------------|
| `main.py` | FastAPI app, endpoints, request orchestration |
| `rules.py` | Deterministic in-process invariants |
| `opa_client.py` | OPA HTTP client with typed errors |
| `rate_limiter.py` | Redis rate limiting + anti-replay |
| `audit.py` | Hash-chain computation + PG persistence |
| `metrics.py` | Thread-safe Prometheus counters/gauges/histograms |
| `models.py` | Pydantic V2 request/response/audit models |
| `settings.py` | Environment-based configuration |

## External dependencies

| Dependency | Version | Purpose |
|-----------|---------|---------|
| PostgreSQL | 16 | Audit trail (append-only) |
| Redis | 7 | Rate limiting, anti-replay |
| OPA | 0.63.0 | Policy evaluation |

## Security boundaries

See [security-narrative.md](security-narrative.md) and [threat-model.md](threat-model.md).

## Deployment

Single Docker Compose stack (`deploy/compose/docker-compose.yml`):
- Verifier: port 8088 (host) → 8000 (container)
- OPA: port 8181
- Redis: port 6379
- Postgres: port 5432

All inter-service communication is on a Docker bridge network.
No TLS between services in dev (expected behind a reverse proxy in production).
