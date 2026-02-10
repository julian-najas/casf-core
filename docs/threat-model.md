# Threat Model — CASF-core Verifier

> **Last updated:** 2026-02-10
> **Scope:** `services/verifier`, `policies/`, `deploy/`

---

## 1. System Overview

The CASF verifier is a **policy-enforcement gateway** that receives AI-tool
invocation requests, evaluates them against OPA/Rego policies, records every
decision in an immutable audit chain, and returns allow/deny.

```
 ┌─────────────┐         ┌──────────┐
 │ Caller      │──HTTP──▶│ Verifier │──gRPC/HTTP──▶ OPA
 │ (LLM/agent) │         │ (FastAPI)│──TCP────────▶ Redis
 └─────────────┘         │          │──TCP────────▶ Postgres
                          └──────────┘
```

### Trust Boundaries

| Boundary | Direction | Trust Level |
|----------|-----------|-------------|
| Caller → Verifier | Inbound | **Untrusted** — every field is validated via Pydantic |
| Verifier → OPA | Outbound | **Semi-trusted** — policies are version-controlled |
| Verifier → Redis | Outbound | **Infrastructure** — assumed available, fail-closed if not |
| Verifier → Postgres | Outbound | **Infrastructure** — same as above |

---

## 2. Threats & Mitigations

### T1 — Request Replay

| | |
|---|---|
| **Attack** | Adversary resends a previously allowed `request_id` to re-execute a tool |
| **Impact** | Duplicate clinical action (e.g., double SMS to patient) |
| **Likelihood** | Medium |
| **Mitigation** | Redis `SET NX EX` on `request_id` with configurable TTL (default 3600 s). Fail-closed: if Redis is down, request is denied. |
| **Residual risk** | After TTL expires, the same `request_id` could be replayed. Acceptable: the audit chain still records both events. |

### T2 — Audit Tampering

| | |
|---|---|
| **Attack** | Attacker with DB access modifies or deletes audit rows |
| **Impact** | Loss of accountability, undetectable policy violations |
| **Likelihood** | Low (requires DB credentials) |
| **Mitigation** | Hash-chain (`prev_hash` links). `export_audit_digest.py` produces a daily digest for external anchoring (WORM, SIEM, GPG-signed file). `event_id` has a UNIQUE constraint; `prev_hash` is NOT NULL. |
| **Residual risk** | If the attacker also controls the anchoring storage, detection is lost. Mitigate with multi-destination anchoring. |

### T3 — Policy Supply-Chain

| | |
|---|---|
| **Attack** | Malicious Rego file is committed that silently allows dangerous operations |
| **Impact** | Bypass of safety controls |
| **Likelihood** | Low for solo dev; medium in team settings |
| **Mitigation** | Rego files tracked in git with code review (CODEOWNERS). OPA policy tests (`opa test`) run in CI. Future: signed policy bundles. |
| **Residual risk** | A reviewer could miss a subtle Rego change. Additional mitigation: diff-based alerting on `policies/` in CI. |

### T4 — Denial of Service

| | |
|---|---|
| **Attack** | Flood the verifier with requests to exhaust Redis/Postgres connections |
| **Impact** | Legitimate requests are denied (fail-closed, so no safety bypass) |
| **Likelihood** | Medium |
| **Mitigation** | Rate limiting at infrastructure level (reverse proxy / API gateway). Redis connection pooling. Uvicorn worker limits. |
| **Residual risk** | The verifier itself does not implement per-caller rate limiting (out of scope for v0.x). |

### T5 — Dependency Compromise

| | |
|---|---|
| **Attack** | A transitive dependency (PyPI, Docker base image, GH Action) is compromised |
| **Impact** | Arbitrary code execution in verifier or CI |
| **Likelihood** | Low but increasing industry-wide |
| **Mitigation** | Dependabot for automated updates. `pip-audit` in CI catches known CVEs. SBOM (CycloneDX) generated per build. Gitleaks scans for leaked secrets. Docker base image pinned (`python:3.11-slim`). |
| **Residual risk** | Zero-day in a dependency before advisory is published. |

---

## 3. Data Classification

| Data | Classification | Storage |
|------|---------------|---------|
| Request payload (tool, params, patient_id) | **PHI-adjacent** | Postgres `audit_events.payload` |
| Decision (allow/deny + violations) | **Operational** | Postgres `audit_events` |
| Hash chain (prev_hash, hash) | **Integrity metadata** | Postgres |
| Daily digest | **Integrity anchor** | External (WORM/SIEM) |
| Redis keys (request_id, rate-limit counters) | **Ephemeral** | Redis (TTL-bound) |

---

## 4. Open Items / Future Work

- [ ] mTLS between verifier and OPA/Redis/Postgres
- [ ] Signed OPA policy bundles
- [ ] Per-caller authentication and rate limiting
- [x] Container image scanning (Trivy) in CI
- [ ] Postgres row-level security for audit table
