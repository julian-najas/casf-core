package casf

default allow = false

# Expect input fields:
# input.tool, input.mode, input.role, input.subject, input.context

is_kill_switch { input.mode == "KILL_SWITCH" }
is_read_only   { input.mode == "READ_ONLY" }
is_normal      { input.mode == "ALLOW" }

has_tenant { input.context.tenant_id != "" }

known_roles := {"receptionist", "nurse", "doctor", "billing", "custodian", "system"}
is_known_role { known_roles[input.role] }

# Utility
deny_with(v) {
  violations := array.concat([], [v])
}

# ---- Tool policies (v1 minimal, safe) ----
# READ tools allowed in NORMAL and READ_ONLY, denied in KILL_SWITCH

allow {
  has_tenant
  is_known_role
  input.tool == "cliniccloud.list_appointments"
  not is_kill_switch
}

allow {
  has_tenant
  is_known_role
  input.tool == "cliniccloud.summary_history"
  not is_kill_switch
  input.subject.patient_id != ""
}

# WRITE tools denied in READ_ONLY and KILL_SWITCH, allowed in ALLOW mode (OPA layer only;
# Redis limiter still enforced separately for twilio.send_sms).

allow {
  has_tenant
  is_known_role
  input.tool == "cliniccloud.create_appointment"
  is_normal
}

allow {
  has_tenant
  is_known_role
  input.tool == "cliniccloud.cancel_appointment"
  is_normal
}

allow {
  has_tenant
  is_known_role
  input.tool == "stripe.generate_invoice"
  is_normal
}

allow {
  has_tenant
  is_known_role
  input.tool == "twilio.send_sms"
  is_normal
  input.subject.patient_id != ""
}

# ---- Violations (optional, helpful for audit/debug) ----
violations[v] {
  is_kill_switch
  v := "Mode_KillSwitch"
}

violations[v] {
  is_read_only
  is_write_tool
  v := "Mode_ReadOnly_NoWrite"
}

is_write_tool {
  input.tool == "cliniccloud.create_appointment"
} or {
  input.tool == "cliniccloud.cancel_appointment"
} or {
  input.tool == "stripe.generate_invoice"
} or {
  input.tool == "twilio.send_sms"
}

violations[v] {
  not has_tenant
  v := "BadRequest_MissingTenantId"
}

violations[v] {
  input.tool == "cliniccloud.summary_history"
  input.subject.patient_id == ""
  v := "BadRequest_MissingPatientId"
}

violations[v] {
  input.tool == "twilio.send_sms"
  input.subject.patient_id == ""
  v := "BadRequest_MissingPatientId"
}

violations[v] {
  not is_known_role
  v := "BadRequest_UnknownRole"
}
