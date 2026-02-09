import uuid
from types import SimpleNamespace

from src.verifier.rate_limiter import RateLimitResult
from src.verifier.rules import apply_rules_v0


def mk_req(*, request_id=None, tool="twilio.send_sms", patient_id="p1"):
    if request_id is None:
        request_id = str(uuid.uuid4())
    subject = {"patient_id": patient_id} if patient_id is not None else {}
    return SimpleNamespace(
        request_id=request_id,
        tool=tool,
        mode="ALLOW",
        role="receptionist",
        subject=subject,
        args={"to": "+34600000000", "template_id": "t1"},
        context={"tenant_id": "t-demo"},
    )

class RLAllowOnce:
    def __init__(self):
        self.calls = 0
    def check(self, key: str, limit: int, window_s: int):
        self.calls += 1
        if self.calls == 1:
            return RateLimitResult(True, 1, "ok")
        return RateLimitResult(False, 2, "limit_exceeded")

class RLThrows:
    def check(self, key: str, limit: int, window_s: int):
        raise RuntimeError("redis down")

def test_sms_missing_patient_id_denies():
    req = mk_req(patient_id=None)
    res = apply_rules_v0(req, rl=RLAllowOnce())
    assert res.decision == "DENY"
    assert "BadRequest_MissingPatientId" in (res.violations or [])

def test_sms_fail_closed_when_rl_none():
    req = mk_req()
    res = apply_rules_v0(req, rl=None)
    assert res.decision == "DENY"
    assert "FAIL_CLOSED" in (res.violations or [])
    assert "Inv_NoSmsBurst" in (res.violations or [])

def test_sms_fail_closed_when_redis_errors():
    req = mk_req()
    res = apply_rules_v0(req, rl=RLThrows())
    assert res.decision == "DENY"
    assert "FAIL_CLOSED" in (res.violations or [])
    assert "Inv_NoSmsBurst" in (res.violations or [])

def test_sms_denies_second_hit_in_window():
    rl = RLAllowOnce()

    r1 = apply_rules_v0(mk_req(request_id="s1"), rl=rl)
    assert r1.decision == "ALLOW"

    r2 = apply_rules_v0(mk_req(request_id="s2"), rl=rl)
    assert r2.decision == "DENY"
    assert "Inv_NoSmsBurst" in (r2.violations or [])
