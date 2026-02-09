package casf

default allow := false
default violations := []
default reason := "denied"

# Helpers
is_read_only {
  input.mode == "READ_ONLY"
}

tool_known {
  input.tool in {
    "cliniccloud.list_appointments",
    "cliniccloud.create_appointment",
    "cliniccloud.cancel_appointment",
    "cliniccloud.summary_history",
    "twilio.send_sms",
    "stripe.generate_invoice",
  }
}

# --- Rules (mínimas) ---

# ALLOW: cliniccloud.list_appointments en READ_ONLY para receptionist
allow {
  tool_known
  input.tool == "cliniccloud.list_appointments"
  is_read_only
  input.role == "receptionist"
}

# DENY unknown tool (con violación explícita)
violations := v {
  not tool_known
  v := ["Tool_Unknown"]
}

reason := r {
  not tool_known
  r := "Unknown tool"
}

# DENY write in READ_ONLY (ejemplo: create_appointment)
violations := v {
  input.tool == "cliniccloud.create_appointment"
  is_read_only
  v := ["Inv_NoWriteSafe"]
}

reason := r {
  input.tool == "cliniccloud.create_appointment"
  is_read_only
  r := "Writes forbidden in READ_ONLY"
}

# DENY twilio.send_sms si rol no permitido (mínimo)
violations := v {
  input.tool == "twilio.send_sms"
  not (input.role in {"receptionist", "admin"})
  v := ["Sms_RoleDenied"]
}

reason := r {
  input.tool == "twilio.send_sms"
  not (input.role in {"receptionist", "admin"})
  r := "Role not allowed to send SMS"
}
