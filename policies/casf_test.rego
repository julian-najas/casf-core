package casf_test

import data.casf

# --- ALLOW ---

test_allow_list_appointments {
    input := {
        "tool": "cliniccloud.list_appointments",
        "mode": "READ_ONLY",
        "role": "receptionist",
        "subject": {"patient_id": "p1"},
        "args": {},
        "context": {"tenant_id": "t1"}
    }
    result := casf.allow with input as input
    result == true
}

# --- DENY ---

test_deny_create_appointment_read_only {
    input := {
        "tool": "cliniccloud.create_appointment",
        "mode": "READ_ONLY",
        "role": "receptionist",
        "subject": {"patient_id": "p1"},
        "args": {},
        "context": {"tenant_id": "t1"}
    }
    result := casf.allow with input as input
    result == false
    violations := casf.violations with input as input
    violations[_] == "Mode_ReadOnly_NoWrite"
}

test_deny_twilio_send_sms_bad_role {
    input := {
        "tool": "twilio.send_sms",
        "mode": "ALLOW",
        "role": "unauthorized_role",
        "subject": {"patient_id": "p1"},
        "args": {},
        "context": {"tenant_id": "t1"}
    }
    result := casf.allow with input as input
    result == false
    violations := casf.violations with input as input
    violations[_] == "BadRequest_UnknownRole"
}

test_deny_unknown_tool {
    input := {
        "tool": "unknown.tool",
        "mode": "ALLOW",
        "role": "receptionist",
        "subject": {"patient_id": "p1"},
        "args": {},
        "context": {"tenant_id": "t1"}
    }
    result := casf.allow with input as input
    result == false
    # No violation específica, pero deniega
}

# --- ALLOW write in ALLOW mode (regression guard for NORMAL→ALLOW fix) ---

test_allow_create_appointment_allow_mode {
    input := {
        "tool": "cliniccloud.create_appointment",
        "mode": "ALLOW",
        "role": "receptionist",
        "subject": {"patient_id": "p1"},
        "args": {},
        "context": {"tenant_id": "t1"}
    }
    result := casf.allow with input as input
    result == true
}

test_allow_twilio_sms_allow_mode {
    input := {
        "tool": "twilio.send_sms",
        "mode": "ALLOW",
        "role": "receptionist",
        "subject": {"patient_id": "p1"},
        "args": {},
        "context": {"tenant_id": "t1"}
    }
    result := casf.allow with input as input
    result == true
}
