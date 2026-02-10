from __future__ import annotations

from .metrics import METRICS
from .models import VerifyRequestV1, VerifyResponseV1
from .rate_limiter import RateLimiter

WRITE_TOOLS = {
    "cliniccloud.create_appointment",
    "cliniccloud.cancel_appointment",
    "twilio.send_sms",
    "stripe.generate_invoice",
}

# READ_ONLY reference defaults (conservative)
READ_ONLY_ALLOWED = {
    "cliniccloud.list_appointments": ["slots_aggregated"],
}

def is_write_tool(tool: str) -> bool:
    return tool in WRITE_TOOLS

def apply_rules_v0(req: VerifyRequestV1, rl: RateLimiter | None = None) -> VerifyResponseV1:
    # Hard requirement: traceability
    patient_id = req.subject.get("patient_id")
    if not patient_id:
        return VerifyResponseV1(
            decision="DENY",
            violations=["BadRequest_MissingPatientId"],
            allowed_outputs=[],
            reason="subject.patient_id required",
        )

    # Rule: No writes in safe modes
    if req.mode in ("READ_ONLY", "KILL_SWITCH") and is_write_tool(req.tool):
        return VerifyResponseV1(
            decision="DENY",
            violations=["Inv_NoWriteSafe"],
            allowed_outputs=[],
            reason=f"No writes allowed in {req.mode}",
        )

    # Allow minimal read-only output for list_appointments
    if req.mode == "READ_ONLY" and req.tool in READ_ONLY_ALLOWED:
        return VerifyResponseV1(
            decision="ALLOW",
            violations=[],
            allowed_outputs=READ_ONLY_ALLOWED[req.tool],
            reason="OK (READ_ONLY degraded output)",
        )

    # SMS rate limit (v1): max 1 SMS / patient / hour
    if req.tool == "twilio.send_sms":
        if rl is None:
            return VerifyResponseV1(
                decision="DENY",
                violations=["FAIL_CLOSED", "Inv_NoSmsBurst"],
                allowed_outputs=[],
                reason="Rate limiter not available",
            )
        key = f"sms:{req.subject['patient_id']}"
        try:
            res_rl = rl.check(key=key, limit=1, window_s=3600)
        except Exception:
            # Redis failure -> FAIL CLOSED for write
            return VerifyResponseV1(
                decision="DENY",
                violations=["FAIL_CLOSED", "Inv_NoSmsBurst"],
                allowed_outputs=[],
                reason="Rate limiter unavailable (fail-closed)",
            )
        if not res_rl.allowed:
            METRICS.inc("casf_rate_limit_deny_total")
            return VerifyResponseV1(
                decision="DENY",
                violations=["Inv_NoSmsBurst"],
                allowed_outputs=[],
                reason="SMS rate limit exceeded",
            )

    # Everything else allowed en v0/v1
    return VerifyResponseV1(
        decision="ALLOW",
        violations=[],
        allowed_outputs=[],
        reason="OK",
    )
