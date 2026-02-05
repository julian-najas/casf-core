import json
import subprocess

def run_curl_test(name, payload, expect_decision):
    cmd = [
        "curl", "-s", "-X", "POST", "http://localhost:8000/verify",
        "-H", "Content-Type: application/json",
        "-d", json.dumps(payload)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        data = json.loads(result.stdout)
    except Exception:
        print(f"{name}: ERROR - No JSON response\n{result.stdout}")
        return
    decision = data.get("decision")
    if decision == expect_decision:
        print(f"{name}: OK ({decision})")
    else:
        print(f"{name}: FAIL (got {decision}, expected {expect_decision})\nResponse: {data}")

if __name__ == "__main__":
    run_curl_test(
        "READ_ONLY + write → DENY",
        {
            "request_id": "r1",
            "tool": "cliniccloud.create_appointment",
            "mode": "READ_ONLY",
            "role": "receptionist",
            "subject": {"patient_id": "p1"},
            "args": {},
            "context": {"timestamp": "2026-02-05T10:00:00Z", "source": "agent"}
        },
        "DENY"
    )
    run_curl_test(
        "READ_ONLY + list_appointments → ALLOW",
        {
            "request_id": "r2",
            "tool": "cliniccloud.list_appointments",
            "mode": "READ_ONLY",
            "role": "receptionist",
            "subject": {"patient_id": "p1"},
            "args": {},
            "context": {"timestamp": "2026-02-05T10:00:00Z", "source": "agent"}
        },
        "ALLOW"
    )
