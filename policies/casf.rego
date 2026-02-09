package casf

default allow = false
	# default violations = []

# Expect input fields:
# input.tool, input.mode, input.role, input.subject, input.context

is_kill_switch { input.mode == "KILL_SWITCH" }
is_read_only   { input.mode == "READ_ONLY" }
is_normal      { input.mode == "NORMAL" }

has_tenant { input.context.tenant_id != "" }

# Utility
deny_with(v) {
  violations := array.concat([], [v])
}

# ---- Tool policies (v1 minimal, safe) ----
# READ tools allowed in NORMAL and READ_ONLY, denied in KILL_SWITCH

allow {
  has_tenant
  input.tool == "cliniccloud.list_appointments"
  not is_kill_switch
}

allow {
  has_tenant
  input.tool == "cliniccloud.summary_history"
  not is_kill_switch
  input.subject.patient_id != ""
}

# WRITE tools denied in READ_ONLY and KILL_SWITCH, allowed in NORMAL (OPA layer only;
# Redis limiter still enforced separately for twilio.send_sms).

allow {
  has_tenant
  input.tool == "cliniccloud.create_appointment"
  is_normal
}

allow {
  has_tenant
  input.tool == "cliniccloud.cancel_appointment"
  is_normal
}

allow {
  has_tenant
  input.tool == "stripe.generate_invoice"
  is_normal
}

allow {
  has_tenant
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
