"""
Minimal in-process metrics — Prometheus text exposition format.

Zero external dependencies.  Thread-safe counters only.
The /metrics endpoint renders them as TYPE counter lines.

Usage:
    from .metrics import METRICS
    METRICS.inc("verify_total")
    METRICS.inc("verify_total", labels={"decision": "ALLOW"})
"""
from __future__ import annotations

import threading
from collections import defaultdict


class _Metrics:
    """Thread-safe counter registry with optional labels."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key = (metric_name, frozen_labels)  →  int
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = defaultdict(int)
        self._help: dict[str, str] = {}

    # ── Public API ───────────────────────────────────────

    def describe(self, name: str, help_text: str) -> None:
        """Register a HELP string for a metric (idempotent)."""
        self._help[name] = help_text

    def inc(self, name: str, *, labels: dict[str, str] | None = None, delta: int = 1) -> None:
        """Increment a counter by *delta* (default 1)."""
        key = (name, _freeze(labels))
        with self._lock:
            self._counters[key] += delta

    def get(self, name: str, *, labels: dict[str, str] | None = None) -> int:
        """Read current value (useful in tests)."""
        key = (name, _freeze(labels))
        with self._lock:
            return self._counters[key]

    def reset(self) -> None:
        """Reset all counters (tests only)."""
        with self._lock:
            self._counters.clear()

    # ── Prometheus text exposition ────────────────────────

    def render(self) -> str:
        """
        Return all counters in Prometheus text exposition format.

        Example output:
            # HELP verify_total Total /verify requests.
            # TYPE verify_total counter
            verify_total{decision="ALLOW"} 42
            verify_total{decision="DENY"} 7
        """
        with self._lock:
            snapshot = dict(self._counters)

        # Group by metric name to emit HELP/TYPE once per name
        by_name: dict[str, list[tuple[tuple[tuple[str, str], ...], int]]] = defaultdict(list)
        for (name, lbl), value in sorted(snapshot.items()):
            by_name[name].append((lbl, value))

        lines: list[str] = []
        for name, entries in sorted(by_name.items()):
            if name in self._help:
                lines.append(f"# HELP {name} {self._help[name]}")
            lines.append(f"# TYPE {name} counter")
            for lbl, value in entries:
                lines.append(f"{name}{_render_labels(lbl)} {value}")

        lines.append("")  # trailing newline
        return "\n".join(lines)


# ── Module-level singleton ───────────────────────────────

METRICS = _Metrics()

# Pre-register descriptions
METRICS.describe("casf_verify_total", "Total /verify requests received.")
METRICS.describe("casf_verify_decision_total", "Verify decisions by outcome.")
METRICS.describe("casf_replay_hit_total", "Anti-replay cache hits (idempotent returns).")
METRICS.describe("casf_replay_mismatch_total", "Anti-replay fingerprint mismatches.")
METRICS.describe("casf_replay_concurrent_total", "Anti-replay concurrent / pending denials.")
METRICS.describe("casf_fail_closed_total", "Fail-closed denials by trigger.")
METRICS.describe("casf_rate_limit_deny_total", "SMS rate-limit denials.")
METRICS.describe("casf_opa_error_total", "OPA evaluation errors.")


# ── Helpers ──────────────────────────────────────────────

def _freeze(labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
    if not labels:
        return ()
    return tuple(sorted(labels.items()))


def _render_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{k}="{v}"' for k, v in labels)
    return "{" + inner + "}"
