from __future__ import annotations

import contextlib
import os

import httpx
import psycopg2
import redis as redis_lib
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .audit import append_audit_event
from .metrics import METRICS
from .models import VerifyRequestV1, VerifyResponseV1
from .opa_client import OpaClient, OpaError
from .rate_limiter import RateLimiter
from .rules import WRITE_TOOLS, apply_rules_v0
from .settings import ANTI_REPLAY_ENABLED, ANTI_REPLAY_TTL_SECONDS, OPA_URL, PG_DSN, REDIS_URL

rl = RateLimiter(REDIS_URL)
opa = OpaClient(OPA_URL)

app = FastAPI(title="CASF Verifier", version="0.1")


# ── Healthchecks ─────────────────────────────────────────

@app.get("/health")
def health():
    """Liveness probe: process is alive."""
    return {"status": "ok"}


@app.get("/healthz")
def healthz():
    """
    Readiness probe: all dependencies reachable and operational.
    Returns 200 only when Postgres, Redis AND OPA are healthy.
    Any single failure → 503.
    """
    checks: dict[str, str] = {}

    # ── Postgres ──
    try:
        conn = psycopg2.connect(PG_DSN, connect_timeout=2)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
        finally:
            conn.close()
        checks["postgres"] = "ok"
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"postgres: {e}") from None

    # ── Redis ──
    try:
        r = redis_lib.Redis.from_url(REDIS_URL, socket_timeout=2, socket_connect_timeout=2)
        r.ping()
        r.close()
        checks["redis"] = "ok"
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"redis: {e}") from None

    # ── OPA (policy evaluable, not just /health) ──
    try:
        with httpx.Client(timeout=2) as c:
            resp = c.post(
                f"{OPA_URL}/v1/data/casf/allow",
                json={"input": {"tool": "healthcheck"}},
            )
            resp.raise_for_status()
        checks["opa"] = "ok"
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"opa: {e}") from None

    return {"status": "ok", "checks": checks}


@app.get("/metrics")
def metrics():
    """Prometheus text exposition endpoint."""
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse(METRICS.render(), media_type="text/plain; version=0.0.4; charset=utf-8")


@app.post("/verify", response_model=VerifyResponseV1)
def verify(req: VerifyRequestV1):
    METRICS.inc("casf_verify_total")
    METRICS.gauge_inc("casf_verify_in_flight")
    try:
        return _verify_inner(req)
    finally:
        METRICS.gauge_dec("casf_verify_in_flight")


def _verify_inner(req: VerifyRequestV1) -> VerifyResponseV1 | JSONResponse:
    with METRICS.timer("casf_verify_duration_seconds"):
        return _verify_core(req)


def _verify_core(req: VerifyRequestV1) -> VerifyResponseV1 | JSONResponse:
    request_body = req.model_dump()

    # ── Anti-replay idempotency gate (must be FIRST) ─────
    # Same request_id + same payload → return cached decision.
    # Same request_id + different payload → DENY (mismatch).
    # Redis failure → FAIL_CLOSED on writes, pass-through on reads.
    replay_result = None
    if ANTI_REPLAY_ENABLED:
        try:
            replay_result = rl.check_replay(
                req.request_id, request_body, ttl_s=ANTI_REPLAY_TTL_SECONDS,
            )
        except Exception:
            if req.tool in WRITE_TOOLS:
                METRICS.inc("casf_verify_decision_total", labels={"decision": "DENY"})
                METRICS.inc("casf_fail_closed_total", labels={"trigger": "redis"})
                return VerifyResponseV1(
                    decision="DENY",
                    violations=["FAIL_CLOSED", "Inv_ReplayCheckUnavailable"],
                    allowed_outputs=[],
                    reason="Replay check unavailable (fail-closed on write)",
                )
            replay_result = None  # fail-open for reads

        if replay_result is not None and not replay_result.is_new:
            # ── Replay detected ──────────────────────────
            if not replay_result.fingerprint_match:
                # Different payload with same request_id → hard deny
                METRICS.inc("casf_verify_decision_total", labels={"decision": "DENY"})
                METRICS.inc("casf_replay_mismatch_total")
                return VerifyResponseV1(
                    decision="DENY",
                    violations=["Inv_ReplayPayloadMismatch"],
                    allowed_outputs=[],
                    reason=f"request_id {req.request_id} already used with different payload",
                )

            # Same payload — return cached decision if available
            if replay_result.cached_decision is not None:
                cached = VerifyResponseV1(**replay_result.cached_decision)
                METRICS.inc("casf_verify_decision_total", labels={"decision": cached.decision})
                METRICS.inc("casf_replay_hit_total")

                # Audit the replay event (best-effort)
                if os.getenv("CASF_DISABLE_AUDIT") != "1":
                    with contextlib.suppress(Exception):
                        append_audit_event(
                            PG_DSN, req, cached,
                            action_override="REPLAY_DETECTED",
                        )

                return cached

            # Decision still pending (concurrent request) — treat as replay deny
            METRICS.inc("casf_verify_decision_total", labels={"decision": "DENY"})
            METRICS.inc("casf_replay_concurrent_total")
            return VerifyResponseV1(
                decision="DENY",
                violations=["Inv_ReplayConcurrent"],
                allowed_outputs=[],
                reason=f"request_id {req.request_id} is being processed concurrently",
            )

    # Apply deterministic rules
    res = apply_rules_v0(req, rl=rl)

    # If we DENY due to missing patient_id, return 400 (schema-level failure)
    if res.violations == ["BadRequest_MissingPatientId"]:
        raise HTTPException(status_code=400, detail=res.reason)

    # System-level FAIL_CLOSED takes precedence over OPA (infra invariant)
    if "FAIL_CLOSED" in res.violations:
        METRICS.inc("casf_verify_decision_total", labels={"decision": "DENY"})
        METRICS.inc("casf_fail_closed_total", labels={"trigger": "rules"})
        if os.getenv("CASF_DISABLE_AUDIT") != "1":
            try:
                append_audit_event(PG_DSN, req, res)
            except Exception:
                res.reason = f"{res.reason} | audit_append_failed"
        return res

    # OPA integration: build input doc
    opa_input = {
        "tool": req.tool,
        "mode": req.mode,
        "role": req.role,
        "subject": req.subject,
        "args": req.args,
        "context": req.context,
    }
    is_write = req.tool in WRITE_TOOLS
    try:
        od = opa.evaluate(opa_input)
    except OpaError as opa_exc:
        METRICS.inc("casf_opa_error_total", labels={"kind": opa_exc.kind})
        # OPA failure: FAIL-CLOSED for writes, FAIL-OPEN for reads (v1 pragmatic)
        if is_write:
            METRICS.inc("casf_verify_decision_total", labels={"decision": "DENY"})
            METRICS.inc("casf_fail_closed_total", labels={"trigger": "opa"})
            return VerifyResponseV1(
                decision="DENY",
                violations=["FAIL_CLOSED", "OPA_Unavailable"],
                allowed_outputs=[],
                reason="OPA unavailable (fail-closed on write)",
            )
        else:
            od = None

    if od is not None and not od.allow:
        METRICS.inc("casf_verify_decision_total", labels={"decision": "DENY"})
        return VerifyResponseV1(
            decision="DENY",
            violations=list(dict.fromkeys(od.violations or ["OPA_Deny"])),
            allowed_outputs=[],
            reason="Denied by OPA policy",
        )

    # Disable audit in tests if flag is set
    if os.getenv("CASF_DISABLE_AUDIT") == "1":
        METRICS.inc("casf_verify_decision_total", labels={"decision": res.decision})
        # Still cache the decision for anti-replay before returning
        if ANTI_REPLAY_ENABLED:
            with contextlib.suppress(Exception):
                rl.store_decision(
                    req.request_id, request_body, res.model_dump(),
                    ttl_s=ANTI_REPLAY_TTL_SECONDS,
                )
        return res

    # Always audit (append-only + hash chain)
    try:
        append_audit_event(PG_DSN, req, res)
    except Exception:
        res.reason = f"{res.reason} | audit_append_failed"
        return JSONResponse(status_code=200, content=res.model_dump())

    # Cache decision in Redis for anti-replay idempotency
    METRICS.inc("casf_verify_decision_total", labels={"decision": res.decision})
    if ANTI_REPLAY_ENABLED:
        with contextlib.suppress(Exception):
            rl.store_decision(
                req.request_id, request_body, res.model_dump(),
                ttl_s=ANTI_REPLAY_TTL_SECONDS,
            )

    return res
