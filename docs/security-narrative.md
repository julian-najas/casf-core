# Security Narrative — CASF-core

> **Audience:** contributors, auditors, future-you.
> For vulnerability reporting, see [SECURITY.md](../SECURITY.md).

## Design Philosophy

CASF (Clinical AI Safety Framework) treats **every AI-tool invocation as untrusted
by default**. The verifier sits between the caller and the tool, enforcing:

1. **Policy-as-code (OPA/Rego):** role × action × mode matrix evaluated on every
   request — no hard-coded allow lists.
2. **Fail-closed:** if OPA, Redis, or Postgres is unreachable the request is
   **denied**, never silently allowed.
3. **Immutable audit chain:** every decision (allow or deny) is appended to a
   hash-linked log in Postgres. Tampering with any row breaks the chain and is
   detectable via `export_audit_digest.py`.
4. **Anti-replay:** `SET NX EX` in Redis rejects duplicate `request_id` values
   within a configurable TTL window.
5. **Rate limiting (fail-closed):** SMS-sending tools enforce per-patient rate
   limits via Redis; if Redis is down the request is denied.

## Trust Boundaries

```
 Caller (LLM / agent)
        │
        ▼
 ┌──────────────┐
 │  Verifier    │──▶ OPA  (policy eval)
 │  (FastAPI)   │──▶ Redis (replay + rate-limit)
 │              │──▶ Postgres (audit chain)
 └──────────────┘
        │
        ▼
   Tool execution (out-of-scope for verifier)
```

The verifier **never** executes the tool itself — it only returns an allow/deny
decision. Tool execution is the caller's responsibility.

## Key Invariants

| Invariant | Enforced by |
|-----------|-------------|
| No decision without audit record | `append_audit_event()` runs inside the request path |
| Hash chain integrity | `prev_hash` links + `export_audit_digest.py` |
| No replay within TTL | Redis `SET NX EX` on `request_id` |
| Deny on infra failure | Every external call is wrapped in try/except → deny |
| Policy changes are versioned | Rego files in `policies/` tracked in git |
