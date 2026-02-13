from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

# ── Error classification ─────────────────────────────────


class OpaError(Exception):
    """Base OPA evaluation error with a kind label for metrics."""

    def __init__(self, kind: str, message: str) -> None:
        self.kind = kind
        super().__init__(message)


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

        Raises OpaError with kind in {timeout, unavailable, bad_status, bad_response}.
        """
        url = f"{self._url}/v1/data/casf"
        payload = {"input": input_doc}

        try:
            with httpx.Client(timeout=self._timeout) as client:
                r = client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise OpaError("timeout", f"OPA request timed out: {exc}") from exc
        except httpx.ConnectError as exc:
            raise OpaError("unavailable", f"OPA unreachable: {exc}") from exc
        except httpx.HTTPError as exc:
            raise OpaError("unavailable", f"OPA HTTP error: {exc}") from exc

        if r.status_code >= 400:
            raise OpaError("bad_status", f"OPA returned {r.status_code}: {r.text[:200]}")

        try:
            body = r.json()
        except Exception as exc:
            raise OpaError("bad_response", f"OPA returned non-JSON: {exc}") from exc

        result = (body or {}).get("result") or {}
        allow = bool(result.get("allow", False))
        violations = result.get("violations") or []
        if not isinstance(violations, list):
            violations = [str(violations)]
        return OpaDecision(allow=allow, violations=[str(v) for v in violations])
