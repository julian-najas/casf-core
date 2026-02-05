from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .audit import append_audit_event
from .models import VerifyRequestV1, VerifyResponseV1
from .rules import apply_rules_v0

def get_pg_dsn() -> str:
    dsn = os.getenv("PG_DSN")
    if not dsn:
        raise RuntimeError("PG_DSN env var is required")
    return dsn

app = FastAPI(title="CASF Verifier", version="0.1")

@app.get("/health")
def health():
    # v0 health = process alive (we add DB ping later)
    return {"status": "ok"}

@app.post("/verify", response_model=VerifyResponseV1)
def verify(req: VerifyRequestV1):
    # Apply deterministic rules
    res = apply_rules_v0(req)

    # If we DENY due to missing patient_id, return 400 (schema-level failure)
    if res.violations == ["BadRequest_MissingPatientId"]:
        raise HTTPException(status_code=400, detail=res.reason)

    # Disable audit in tests if flag is set
    if os.getenv("CASF_DISABLE_AUDIT") == "1":
        return res

    # Always audit (append-only + hash chain)
    try:
        append_audit_event(get_pg_dsn(), req, res)
    except Exception as e:
        # Audit failure policy v0:
        # - do NOT block the response (we'll tighten later with mode latching / fail-closed writes)
        # - but surface a hard signal in headers/body is avoided in v0 to keep UX stable
        # For now, we still return decision but mark reason.
        res.reason = f"{res.reason} | audit_append_failed"
        return JSONResponse(status_code=200, content=res.model_dump())

    return res
