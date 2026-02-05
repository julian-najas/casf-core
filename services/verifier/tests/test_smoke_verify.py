def test_smoke_verify():
    from verifier.rules import verify_rules
    class Dummy:
        payload = {"valid": True}
    req = Dummy()
    result = verify_rules(req)
    assert result["decision"] == "allow"
