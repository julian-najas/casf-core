from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
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
    subject: Dict[str, str]
    args: Dict[str, Any]
    context: Dict[str, Any]

class VerifyResponseV1(BaseModel):
    decision: Decision
    violations: List[str] = []
    allowed_outputs: List[str] = []
    reason: Optional[str] = None

class AuditEventV1(BaseModel):
    event_id: str
    request_id: str
    ts: str
    actor: str
    action: str
    decision: str
    payload: Dict[str, Any]
    prev_hash: str
    hash: str
