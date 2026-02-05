from __future__ import annotations

from typing import List, Tuple

from .models import VerifyRequestV1, VerifyResponseV1

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

def apply_rules_v0(req: VerifyRequestV1) -> VerifyResponseV1:
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

    # Everything else allowed in v0 (we tighten later with Redis + OPA)
    return VerifyResponseV1(
        decision="ALLOW",
        violations=[],
        allowed_outputs=[],
        reason="OK",
    )
