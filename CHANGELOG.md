# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security
- **Dockerfile multi-stage build** — separate `builder` and `runtime` stages;
  runtime runs as non-root user `appuser` (UID 10001) with `HEALTHCHECK`.
- **`.dockerignore`** — excludes tests, `.venv`, caches, IDE files, and `.git`
  from the Docker build context, reducing image size and attack surface.

### Changed
- **Centralised test helpers** — extracted `FakeRedis`, `get_client`,
  `isolated_client`, `make_request`, `make_response`, and shared payload
  constants into `tests/helpers.py`; reduced `conftest.py` to `sys.path` setup
  only. All 6 test files now import from `helpers` — zero duplication.
- **mypy strict mode** — `pyproject.toml` enables `strict = true`;
  all 11 source modules pass with zero errors. Added `py.typed` marker.
- **`__all__` exports** — every public module declares `__all__` for explicit API surface.

### Added
- **GitHub issue templates** — `bug_report.yml` and `feature_request.yml`
  (YAML-based forms with component dropdown).
- **PR template** — checklist covering tests, mypy, ruff, OPA, CHANGELOG, and secrets.
- **README badges** — mypy strict, ruff code style, Apache-2.0 license.
- **Structured logging** — `structlog` JSON output with context-bound variables
  (`request_id`, `tool`, `role`, `mode`) propagated via `contextvars`. Log events:
  `verify_start`, `verify_decision`, `replay_hit`, `replay_mismatch`,
  `fail_closed`, `opa_error`, `audit_append_failed`.
- **`logging.py`** — centralised `setup_logging()` + `get_logger()`, configurable
  via `LOG_LEVEL` and `LOG_FORMAT` env vars.
- **Typed Pydantic models** — `SubjectV1`, `ContextV1` with field validation
  (`patient_id` min_length=1, `tenant_id` min_length=1, `extra="allow"`).
  `request_id`, `event_id` are now `uuid.UUID` (was bare `str`).
- **Fail-closed on audit failure** — if Postgres audit append fails, the verifier
  returns `DENY` with `FAIL_CLOSED` + `Audit_Unavailable` violations.
  New metric: `casf_fail_closed_total{trigger="postgres"}`.
- **`test_audit_fail_closed.py`** — regression test for audit-failure deny path.
- **`docs/architecture.md`** — component diagram, request flow, key design
  decisions, module map, external dependencies.
- **`docs/operability.md`** — health endpoints, failure modes, restart/recovery,
  scaling, log inspection, runbook, backup/restore, monitoring alerts.
- **`.env.example`** — reference environment configuration.
- **`CODE_OF_CONDUCT.md`** — Contributor Covenant v2.1.
- **Lock files** — `requirements.lock` and `requirements-dev.lock` for
  reproducible installs.
- **`make fmt`** — auto-format code (ruff format + ruff check --fix).
- **`make build`** — build Docker image.
- **`make fmt-check`** / **`make check`** — CI-ready gates (lint + format + test + OPA).
- **CI: ruff format check** — added `ruff format --check` step to lint job.
- **Release process** — documented in `CONTRIBUTING.md` with strict SemVer rules.
- **Observability: `/metrics` endpoint** — Prometheus text exposition format,
  zero external dependencies, thread-safe counters:
  - `casf_verify_total` — total `/verify` requests
  - `casf_verify_decision_total{decision}` — decisions by ALLOW/DENY
  - `casf_verify_duration_seconds` — **histogram** latency of `/verify` requests
  - `casf_verify_in_flight` — **gauge** for concurrent requests
  - `casf_replay_hit_total` — anti-replay cache hits (idempotent returns)
  - `casf_replay_mismatch_total` — payload fingerprint mismatches
  - `casf_replay_concurrent_total` — concurrent pending denials
  - `casf_fail_closed_total{trigger}` — fail-closed denials by trigger (`redis`, `opa`, `rules`, `postgres`)
  - `casf_rate_limit_deny_total` — SMS rate-limit denials
  - `casf_opa_error_total{kind}` — OPA errors by kind (`timeout`, `unavailable`, `bad_status`, `bad_response`)
- **`docs/observability.md`** — cardinality rules, allowed labels, forbidden labels governance.
- **OPA error classification** — `OpaError` with kind label for typed failure metrics.

### Changed
- **Anti-replay upgraded to idempotent cached decision:** same `request_id` +
  same payload returns the cached decision (200) instead of 409. Different
  payload with same `request_id` returns `DENY` (`Inv_ReplayPayloadMismatch`).
- **`model_dump(mode="json")`** — all Pydantic serializations use JSON mode for
  stable datetime/UUID strings (replay fingerprinting, OPA payloads, audit).
- **`_canonical_json`** — handles `uuid.UUID` and `datetime` via custom `default`.
- **`psycopg2.extras.register_uuid()`** — native UUID handling in Postgres driver.
- **`compute_hash`** — accepts `str | uuid.UUID` for `request_id` / `event_id`.
- **Contract** — `request.v1.json` `request_id` now has `"format": "uuid"`.
- **Test isolation** — all test files use `_get_client()` with `importlib.reload`
  and OPA mocking (`patch.object`) to avoid external dependencies.
- **`structlog` dependency** — added to `pyproject.toml` runtime deps.
- **`pytest-cov`** — added to dev deps; `--cov-fail-under=80` enforced.
- `REPLAY_DETECTED` audit event logged on every replay.
- Configuration: `ANTI_REPLAY_ENABLED`, `ANTI_REPLAY_TTL_SECONDS`.
- Threat model T1 closed as **Mitigated**.

### Added
- **Security scan CI job:** `pip-audit` (known CVEs), Gitleaks (secrets detection),
  CycloneDX SBOM generation, and Trivy container image scanning.
- **Dependabot:** automated weekly updates for pip, GitHub Actions, and Docker
  dependencies (`.github/dependabot.yml`).
- **SECURITY.md:** full security policy with vulnerability reporting process,
  scope, and disclosure policy.
- **Threat model:** `docs/threat-model.md` — T1–T5 threats with mitigations,
  data classification, and open items.
- **Security narrative:** `docs/security-narrative.md` — design philosophy,
  trust boundaries, and key invariants.

### Changed
- GitHub Actions pinned to full SHA hashes (supply-chain hardening against
  tag hijacking). Version tags preserved in comments for Dependabot.

## [0.8.1] - 2026-02-09

### Added
- Anti-replay gate: duplicate `request_id` rejected (409) within 24 h (Redis `SET NX EX`).
- Audit digest export script (`export_audit_digest.py`) — anchor-ready for WORM/SIEM.
- `CHANGELOG.md`, `CONTRIBUTING.md`, `CODEOWNERS`, `Makefile`, pre-commit config.

### Fixed
- `prev_hash` now inserts `""` (not NULL) for genesis — aligns DDL, code, and contract.
- `AuditEventV1.decision` typed as `Decision` (Literal), not bare `str`.
- CI badge points to `julian-najas/casf-core`.

## [0.8.0] - 2026-02-09

### Added
- Apache-2.0 LICENSE.
- GitHub Actions CI: 3 jobs (lint, test, opa-test).
- `.gitignore` (comprehensive Python/IDE/OS/Docker patterns).
- Rewritten `README.md` with architecture diagram, quick start, guarantees.

### Fixed
- CI: OPA runs as sidecar only (no service container port conflict).
- Removed dead `smoke_test.py` from repo.
- Contract `request.v1.json`: `tenant_id` required, `timestamp`/`source` optional.
- Removed stray tab in `casf.rego`.

### Changed
- ruff + mypy configured and enforced (38 auto-fixes + 5 manual).

## [0.7.0] - 2026-02-09

### Fixed
- OPA mode: `is_normal` now matches `"ALLOW"` (was `"NORMAL"` — never matched).
- Removed duplicate policy dir `services/opa/policy/` — `policies/` is single source of truth.
- Added `known_roles` set + `is_known_role` guard in Rego (unknown roles → DENY).
- Aligned `audit_event.v1.json` schema with actual `AuditEventV1` model.

### Added
- `BadRequest_UnknownRole` violation in OPA policy.
- Regression tests for ALLOW mode in OPA.

## [0.6.0] - 2026-02-09

### Added
- Integration smoke test (`smoke_pr3.ps1`): 5-check full-stack verification.
- FAIL_CLOSED short-circuit in `/verify` before OPA consultation.

## [0.5.0] - 2026-02-09

### Added
- `/healthz` semantic readiness probe (Postgres + Redis + OPA reachable).
- Dockerfile COPY order fix (src before pip install).

## [0.4.0] - 2026-02-09

### Added
- Redis rate limiting for `twilio.send_sms` (1 SMS / patient_id / hour).
- Fail-closed on writes when Redis unavailable.
- 4 rate-limit tests.

## [0.3.0] - 2026-02-09

### Added
- Append-only audit trail with SHA-256 hash chain.
- Advisory lock serialisation (`pg_advisory_xact_lock(42)`).
- 9 audit chain tests.

## [0.2.0] - 2026-02-09

### Added
- Initial skeleton: FastAPI verifier, OPA integration, Docker Compose stack.
- Contracts (JSON schemas + enums), OPA Rego policies, Postgres DDL.
- Basic `/health`, `/verify` endpoints.
- 6 OPA policy tests.

[Unreleased]: https://github.com/julian-najas/casf-core/compare/v0.12.0...HEAD
[0.8.1]: https://github.com/julian-najas/casf-core/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/julian-najas/casf-core/compare/v0.7.0-freeze...v0.8.0
[0.7.0]: https://github.com/julian-najas/casf-core/compare/v0.6-redis-rate-limit...v0.7.0-freeze
[0.6.0]: https://github.com/julian-najas/casf-core/compare/v0.5-tests-green...v0.6-redis-rate-limit
[0.5.0]: https://github.com/julian-najas/casf-core/compare/v0.4-verifier-v0...v0.5-tests-green
[0.4.0]: https://github.com/julian-najas/casf-core/compare/v0.3-tests...v0.4-verifier-v0
[0.3.0]: https://github.com/julian-najas/casf-core/compare/v0.2-verifier-v0...v0.3-tests
[0.2.0]: https://github.com/julian-najas/casf-core/releases/tag/v0.2-verifier-v0
