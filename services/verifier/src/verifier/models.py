from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Mode = Literal["ALLOW", "STEP_UP", "READ_ONLY", "KILL_SWITCH"]
Role = Literal["receptionist", "nurse", "doctor", "billing", "custodian", "system"]
Tool = Literal[
    "cliniccloud.create_appointment",
    "cliniccloud.cancel_appointment",
    "cliniccloud.list_appointments",
    "cliniccloud.summary_history",
    "twilio.send_sms",
    "stripe.generate_invoice",
]
Decision = Literal["ALLOW", "DENY", "NEEDS_APPROVAL"]

class VerifyRequestV1(BaseModel):
    request_id: str = Field(..., description="Idempotent request identifier (UUID or stable string).")
    tool: Tool
    mode: Mode
    role: Role
    subject: dict[str, str]
    args: dict[str, Any]
    context: dict[str, Any]

class VerifyResponseV1(BaseModel):
    decision: Decision
    violations: list[str] = []
    allowed_outputs: list[str] = []
    reason: str | None = None

class AuditEventV1(BaseModel):
    event_id: str
    request_id: str
    ts: str
    actor: str
    action: str
    decision: str
    payload: dict[str, Any]
    prev_hash: str
    hash: str
