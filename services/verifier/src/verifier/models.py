from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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


class SubjectV1(BaseModel):
    model_config = ConfigDict(extra="allow")

    patient_id: str = Field(..., min_length=1)


class ContextV1(BaseModel):
    model_config = ConfigDict(extra="allow")

    tenant_id: str = Field(..., min_length=1)
    timestamp: datetime | None = None
    source: str | None = None
    session_id: str | None = None
    ip: str | None = None


class VerifyRequestV1(BaseModel):
    request_id: uuid.UUID = Field(..., description="Idempotent request identifier (UUID).")
    tool: Tool
    mode: Mode
    role: Role
    subject: SubjectV1
    args: dict[str, Any]
    context: ContextV1


class VerifyResponseV1(BaseModel):
    decision: Decision
    violations: list[str] = []
    allowed_outputs: list[str] = []
    reason: str | None = None


class AuditEventV1(BaseModel):
    event_id: uuid.UUID
    request_id: uuid.UUID
    ts: str
    actor: str
    action: str
    decision: Decision
    payload: dict[str, Any]
    prev_hash: str
    hash: str
