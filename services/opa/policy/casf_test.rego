package casf

# ---- Fixtures ----
base_ctx := {"tenant_id": "t1"}

# ---- ALLOW esperado ----
test_allow_list_appointments_read_only_receptionist {
  allow with input as {
    "tool": "cliniccloud.list_appointments",
    "mode": "READ_ONLY",
    "role": "receptionist",
    "subject": {"patient_id": "p1"},
    "args": {},
    "context": base_ctx,
  }
}

# ---- DENY: write en READ_ONLY ----
test_deny_create_appointment_read_only_has_violation {
  not allow with input as {
    "tool": "cliniccloud.create_appointment",
    "mode": "READ_ONLY",
    "role": "receptionist",
    "subject": {"patient_id": "p1"},
    "args": {},
    "context": base_ctx,
  }

  some v
  v := violations with input as {
    "tool": "cliniccloud.create_appointment",
    "mode": "READ_ONLY",
    "role": "receptionist",
    "subject": {"patient_id": "p1"},
    "args": {},
    "context": base_ctx,
  }

  "Inv_NoWriteSafe" in v
}

# ---- DENY: tool desconocida ----
test_deny_unknown_tool_has_violation {
  not allow with input as {
    "tool": "unknown.do_thing",
    "mode": "READ_ONLY",
    "role": "receptionist",
    "subject": {"patient_id": "p1"},
    "args": {},
    "context": base_ctx,
  }

  some v
  v := violations with input as {
    "tool": "unknown.do_thing",
    "mode": "READ_ONLY",
    "role": "receptionist",
    "subject": {"patient_id": "p1"},
    "args": {},
    "context": base_ctx,
  }

  "Tool_Unknown" in v
}

# ---- DENY: twilio.send_sms rol no autorizado ----
test_deny_sms_role_denied_has_violation {
  not allow with input as {
    "tool": "twilio.send_sms",
    "mode": "ALLOW",
    "role": "intern",
    "subject": {"patient_id": "p1"},
    "args": {"to": "+34600000000", "template_id": "t1"},
    "context": base_ctx,
  }

  some v
  v := violations with input as {
    "tool": "twilio.send_sms",
    "mode": "ALLOW",
    "role": "intern",
    "subject": {"patient_id": "p1"},
    "args": {"to": "+34600000000", "template_id": "t1"},
    "context": base_ctx,
  }

  "Sms_RoleDenied" in v
}
