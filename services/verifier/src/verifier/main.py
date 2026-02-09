from __future__ import annotations

import os

import httpx
import psycopg2
import redis as redis_lib
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse


from .audit import append_audit_event
from .models import VerifyRequestV1, VerifyResponseV1
from .rules import apply_rules_v0
from .settings import PG_DSN, REDIS_URL, OPA_URL
from .opa_client import OpaClient
from .rate_limiter import RateLimiter



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
        raise HTTPException(status_code=503, detail=f"postgres: {e}")

    # ── Redis ──
    try:
        r = redis_lib.Redis.from_url(REDIS_URL, socket_timeout=2, socket_connect_timeout=2)
        r.ping()
        r.close()
        checks["redis"] = "ok"
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"redis: {e}")

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
        raise HTTPException(status_code=503, detail=f"opa: {e}")

    return {"status": "ok", "checks": checks}



@app.post("/verify", response_model=VerifyResponseV1)
def verify(req: VerifyRequestV1):
    # Apply deterministic rules
    res = apply_rules_v0(req, rl=rl)

    # If we DENY due to missing patient_id, return 400 (schema-level failure)
    if res.violations == ["BadRequest_MissingPatientId"]:
        raise HTTPException(status_code=400, detail=res.reason)

    # System-level FAIL_CLOSED takes precedence over OPA (infra invariant)
    if "FAIL_CLOSED" in res.violations:
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
    WRITE_TOOLS = {
        "cliniccloud.create_appointment",
        "cliniccloud.cancel_appointment",
        "stripe.generate_invoice",
        "twilio.send_sms",
    }
    is_write = req.tool in WRITE_TOOLS
    try:
        od = opa.evaluate(opa_input)
    except Exception:
        # OPA failure: FAIL-CLOSED for writes, FAIL-OPEN for reads (v1 pragmatic)
        if is_write:
            return VerifyResponseV1(
                decision="DENY",
                violations=["FAIL_CLOSED", "OPA_Unavailable"],
                allowed_outputs=[],
                reason="OPA unavailable (fail-closed on write)",
            )
        else:
            od = None

    if od is not None and not od.allow:
        return VerifyResponseV1(
            decision="DENY",
            violations=list(dict.fromkeys(od.violations or ["OPA_Deny"])),
            allowed_outputs=[],
            reason="Denied by OPA policy",
        )

    # Disable audit in tests if flag is set
    if os.getenv("CASF_DISABLE_AUDIT") == "1":
        return res

    # Always audit (append-only + hash chain)
    try:
        append_audit_event(PG_DSN, req, res)
    except Exception as e:
        # Audit failure policy v0:
        # - do NOT block the response (we'll tighten later with mode latching / fail-closed writes)
        # - but surface a hard signal in headers/body is avoided in v0 to keep UX stable
        # For now, we still return decision but mark reason.
        res.reason = f"{res.reason} | audit_append_failed"
        return JSONResponse(status_code=200, content=res.model_dump())

    return res
