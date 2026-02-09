from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class OpaDecision:
    allow: bool
    violations: list[str]

class OpaClient:
    def __init__(self, opa_url: str, timeout_s: float = 0.35):
        self._url = opa_url.rstrip("/")
        self._timeout = timeout_s

    def evaluate(self, input_doc: dict[str, Any]) -> OpaDecision:
        """
        Calls OPA data API:
          POST {OPA_URL}/v1/data/casf
        expecting result.allow (bool) and result.violations (array)
        """
        url = f"{self._url}/v1/data/casf"
        payload = {"input": input_doc}

        with httpx.Client(timeout=self._timeout) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
            body = r.json()

        result = (body or {}).get("result") or {}
        allow = bool(result.get("allow", False))
        violations = result.get("violations") or []
        if not isinstance(violations, list):
            violations = [str(violations)]
        return OpaDecision(allow=allow, violations=[str(v) for v in violations])
