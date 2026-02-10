# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.x     | :white_check_mark: |

Only the latest release on `main` receives security fixes.

## Reporting a Vulnerability

> **Do NOT open a public issue.**

1. Email **security@casf-core.dev** (or the address listed in `CODEOWNERS`).
2. Include:
   - Description of the vulnerability and potential impact.
   - Steps to reproduce or a minimal proof-of-concept.
   - Affected component (`verifier`, `policies`, `deploy`, etc.).
3. You will receive an acknowledgement within **48 hours**.
4. We aim to release a fix within **7 days** for critical issues.

## Scope

The following components are in-scope for this policy:

| Component | Path | Notes |
|-----------|------|-------|
| Verifier service | `services/verifier/` | FastAPI app, audit chain, anti-replay |
| OPA policies | `policies/` | Rego policy files |
| SQL schema | `deploy/sql/` | Postgres init scripts |
| CI/CD | `.github/workflows/` | GitHub Actions |
| Docker | `services/verifier/Dockerfile`, `deploy/compose/` | Container config |

Out-of-scope: forked copies, third-party dependencies (report upstream), and the
caller/agent that invokes the verifier.

## Disclosure Policy

- We follow **coordinated disclosure**: we will credit the reporter (unless they
  prefer anonymity) and publish a brief advisory in `CHANGELOG.md` once the fix
  is released.
- CVE assignment will be requested for issues with CVSS ≥ 7.0.

## Replay Protection

Every `request_id` is tracked via Redis with a configurable TTL (default 24 h).

| Scenario | Behaviour |
|----------|----------|
| Same `request_id` + same payload | Returns cached decision (idempotent) |
| Same `request_id` + different payload | `DENY` — `Inv_ReplayPayloadMismatch` |
| Redis unavailable + write tool | `DENY` — fail-closed |
| Redis unavailable + read tool | Pass-through (fail-open) |

Replay events are audited as `REPLAY_DETECTED` in the hash-chained audit trail.

Configuration:
- `ANTI_REPLAY_ENABLED` (default `true`)
- `ANTI_REPLAY_TTL_SECONDS` (default `86400`)

## Security Controls

See [docs/security-narrative.md](docs/security-narrative.md) for the design
philosophy and [docs/threat-model.md](docs/threat-model.md) for the threat
model.
