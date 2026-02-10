"""
Minimal in-process metrics — Prometheus text exposition format.

Zero external dependencies.  Thread-safe counters, gauges, and histograms.
The /metrics endpoint renders them in standard Prometheus format.

Usage:
    from .metrics import METRICS
    METRICS.inc("verify_total")
    METRICS.inc("verify_total", labels={"decision": "ALLOW"})
    METRICS.observe("verify_duration_seconds", 0.042)
    METRICS.gauge_inc("verify_in_flight")
    METRICS.gauge_dec("verify_in_flight")
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from contextlib import contextmanager


class _Metrics:
    """Thread-safe metric registry: counters, gauges, histograms."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = defaultdict(int)
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], int] = defaultdict(int)
        # histograms: name → (buckets, {frozen_labels → [bucket_counts..., +Inf]}, {frozen_labels → (sum, count)})
        self._hist_buckets: dict[str, tuple[float, ...]] = {}
        self._hist_counts: dict[str, dict[tuple[tuple[str, str], ...], list[int]]] = {}
        self._hist_sums: dict[str, dict[tuple[tuple[str, str], ...], list[float]]] = {}
        self._help: dict[str, str] = {}
        self._types: dict[str, str] = {}  # name → "counter" | "gauge" | "histogram"

    # ── Registration ─────────────────────────────────────

    def describe(self, name: str, help_text: str, metric_type: str = "counter") -> None:
        """Register HELP string and TYPE for a metric (idempotent)."""
        self._help[name] = help_text
        self._types[name] = metric_type

    def register_histogram(
        self,
        name: str,
        help_text: str,
        buckets: tuple[float, ...] = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    ) -> None:
        """Register a histogram with explicit bucket boundaries."""
        self._help[name] = help_text
        self._types[name] = "histogram"
        self._hist_buckets[name] = buckets
        self._hist_counts[name] = defaultdict(lambda: [0] * (len(buckets) + 1))  # +1 for +Inf
        self._hist_sums[name] = defaultdict(lambda: [0.0, 0])  # [sum, count]

    # ── Counter API ──────────────────────────────────────

    def inc(self, name: str, *, labels: dict[str, str] | None = None, delta: int = 1) -> None:
        key = (name, _freeze(labels))
        with self._lock:
            self._counters[key] += delta

    def get(self, name: str, *, labels: dict[str, str] | None = None) -> int:
        key = (name, _freeze(labels))
        with self._lock:
            return self._counters[key]

    # ── Gauge API ────────────────────────────────────────

    def gauge_inc(self, name: str, *, labels: dict[str, str] | None = None) -> None:
        key = (name, _freeze(labels))
        with self._lock:
            self._gauges[key] += 1

    def gauge_dec(self, name: str, *, labels: dict[str, str] | None = None) -> None:
        key = (name, _freeze(labels))
        with self._lock:
            self._gauges[key] -= 1

    def gauge_get(self, name: str, *, labels: dict[str, str] | None = None) -> int:
        key = (name, _freeze(labels))
        with self._lock:
            return self._gauges[key]

    # ── Histogram API ────────────────────────────────────

    def observe(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        """Record an observation into a histogram."""
        frozen = _freeze(labels)
        with self._lock:
            buckets = self._hist_buckets.get(name)
            if buckets is None:
                return
            counts = self._hist_counts[name][frozen]
            for i, bound in enumerate(buckets):
                if value <= bound:
                    counts[i] += 1
            counts[-1] += 1  # +Inf always
            sums = self._hist_sums[name][frozen]
            sums[0] += value
            sums[1] += 1

    @contextmanager
    def timer(self, name: str, *, labels: dict[str, str] | None = None):
        """Context manager that observes elapsed time into a histogram."""
        start = time.monotonic()
        try:
            yield
        finally:
            self.observe(name, time.monotonic() - start, labels=labels)

    # ── Reset (tests only) ───────────────────────────────

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            for name in self._hist_counts:
                self._hist_counts[name].clear()
                self._hist_sums[name].clear()

    # ── Prometheus text exposition ────────────────────────

    def render(self) -> str:
        with self._lock:
            counter_snap = dict(self._counters)
            gauge_snap = dict(self._gauges)
            hist_snap = {
                name: (
                    self._hist_buckets[name],
                    {k: list(v) for k, v in self._hist_counts[name].items()},
                    {k: list(v) for k, v in self._hist_sums[name].items()},
                )
                for name in self._hist_buckets
            }

        lines: list[str] = []

        # Counters
        _render_flat(lines, counter_snap, self._help, "counter", self._types)

        # Gauges
        _render_flat(lines, gauge_snap, self._help, "gauge", self._types)

        # Histograms
        for name in sorted(hist_snap):
            buckets, counts_by_lbl, sums_by_lbl = hist_snap[name]
            if name in self._help:
                lines.append(f"# HELP {name} {self._help[name]}")
            lines.append(f"# TYPE {name} histogram")
            for frozen_lbl in sorted(counts_by_lbl):
                bucket_counts = counts_by_lbl[frozen_lbl]
                sum_count = sums_by_lbl.get(frozen_lbl, [0.0, 0])
                cumulative = 0
                for i, bound in enumerate(buckets):
                    cumulative += bucket_counts[i]
                    lines.append(f"{name}_bucket{_render_labels((*frozen_lbl, ('le', str(bound))))} {cumulative}")
                cumulative += bucket_counts[-1] - sum(bucket_counts[:-1])  # already counted above
                lines.append(f"{name}_bucket{_render_labels((*frozen_lbl, ('le', '+Inf')))} {sum_count[1]}")
                lines.append(f"{name}_sum{_render_labels(frozen_lbl)} {sum_count[0]:.6f}")
                lines.append(f"{name}_count{_render_labels(frozen_lbl)} {sum_count[1]}")

        lines.append("")
        return "\n".join(lines)


# ── Module-level singleton ───────────────────────────────

METRICS = _Metrics()

# Counters
METRICS.describe("casf_verify_total", "Total /verify requests received.")
METRICS.describe("casf_verify_decision_total", "Verify decisions by outcome.")
METRICS.describe("casf_replay_hit_total", "Anti-replay cache hits (idempotent returns).")
METRICS.describe("casf_replay_mismatch_total", "Anti-replay fingerprint mismatches.")
METRICS.describe("casf_replay_concurrent_total", "Anti-replay concurrent / pending denials.")
METRICS.describe("casf_fail_closed_total", "Fail-closed denials by trigger.")
METRICS.describe("casf_rate_limit_deny_total", "SMS rate-limit denials.")
METRICS.describe("casf_opa_error_total", "OPA evaluation errors by kind.")

# Gauge
METRICS.describe("casf_verify_in_flight", "Requests currently being processed.", metric_type="gauge")

# Histogram
METRICS.register_histogram(
    "casf_verify_duration_seconds",
    "Latency of /verify requests in seconds.",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)


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


def _render_flat(
    lines: list[str],
    snapshot: dict[tuple[str, tuple[tuple[str, str], ...]], int],
    help_texts: dict[str, str],
    default_type: str,
    types: dict[str, str],
) -> None:
    """Render counter or gauge metrics grouped by name."""
    by_name: dict[str, list[tuple[tuple[tuple[str, str], ...], int]]] = defaultdict(list)
    for (name, lbl), value in sorted(snapshot.items()):
        by_name[name].append((lbl, value))

    for name, entries in sorted(by_name.items()):
        metric_type = types.get(name, default_type)
        if name in help_texts:
            lines.append(f"# HELP {name} {help_texts[name]}")
        lines.append(f"# TYPE {name} {metric_type}")
        for lbl, value in entries:
            lines.append(f"{name}{_render_labels(lbl)} {value}")
