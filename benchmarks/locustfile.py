"""
CASF Verifier — Locust performance benchmark suite.

Scenarios:
 1. read_allow    — list_appointments as doctor (ALLOW path, fast)
 2. write_allow   — create_appointment as doctor (ALLOW + audit)
 3. write_deny    — send_sms as receptionist (DENY — rate-limit or OPA)
 4. healthz       — readiness probe (Postgres + Redis + OPA round-trip)

Usage:
    # Headless run (CI / make bench)
    locust --headless -u 20 -r 5 --run-time 30s -H http://localhost:8088

    # Interactive Web UI
    locust -H http://localhost:8088
    # then open http://localhost:8089

Requirements:
    pip install locust
"""
from __future__ import annotations

import uuid

from locust import HttpUser, between, task


def _verify_payload(
    tool: str,
    role: str,
    mode: str = "ALLOW",
    patient_id: str = "P-bench-001",
    tenant_id: str = "t-bench",
) -> dict[str, object]:
    """Build a minimal /verify JSON body."""
    return {
        "request_id": str(uuid.uuid4()),
        "tool": tool,
        "mode": mode,
        "role": role,
        "subject": {"patient_id": patient_id},
        "args": {},
        "context": {"tenant_id": tenant_id},
    }


class VerifierUser(HttpUser):
    """Simulates a mixed workload against the CASF Verifier."""

    wait_time = between(0.1, 0.5)

    # ── Read path (fast, no audit write) ─────────────────

    @task(5)
    def read_allow(self) -> None:
        """Doctor lists appointments — expected ALLOW."""
        self.client.post(
            "/verify",
            json=_verify_payload(
                tool="cliniccloud.list_appointments",
                role="doctor",
            ),
            name="/verify [read_allow]",
        )

    # ── Write path (audit + OPA) ─────────────────────────

    @task(3)
    def write_allow(self) -> None:
        """Doctor creates appointment — expected ALLOW + audit."""
        self.client.post(
            "/verify",
            json=_verify_payload(
                tool="cliniccloud.create_appointment",
                role="doctor",
            ),
            name="/verify [write_allow]",
        )

    # ── Deny path (rate-limit / policy) ──────────────────

    @task(2)
    def write_deny(self) -> None:
        """Receptionist sends SMS — may be rate-limited or policy denied."""
        self.client.post(
            "/verify",
            json=_verify_payload(
                tool="twilio.send_sms",
                role="receptionist",
                patient_id=f"P-bench-{uuid.uuid4().hex[:6]}",
            ),
            name="/verify [write_deny]",
        )

    # ── Health probe ─────────────────────────────────────

    @task(1)
    def healthz(self) -> None:
        """Readiness probe — round-trip to all dependencies."""
        self.client.get("/healthz", name="/healthz")
