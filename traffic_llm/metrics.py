"""Evaluation: turn a run's per-tick stream into a competence / safety /
robustness scorecard.

- competence: did traffic flow well? (throughput, travel time, wait, queues)
- safety:     did the controller try unsafe things, and did the system gridlock?
- robustness: after each shock, how fast did it recover — gracefully or not?
"""

from __future__ import annotations

import statistics
from typing import Any, Optional


def _percentile(xs: list[int], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return float(s[k])


SHOCK_EVENT_TYPES = {"closure", "surge"}


class MetricsCollector:
    def __init__(self) -> None:
        self.ticks: list[int] = []
        self.total_queue: list[int] = []
        self.discharged: list[int] = []
        self.gridlocked: list[bool] = []
        self.shock_ticks: list[int] = []

        self.decision_count = 0
        self.llm_failures = 0
        self.backend_ms: list[float] = []
        self.rejected_by_reason: dict[str, int] = {}
        self.rejected_total = 0
        self.usage_in = 0
        self.usage_out = 0
        self.usage_cache_read = 0

    def update_tick(self, snap: dict[str, Any]) -> None:
        self.ticks.append(snap["tick"])
        self.total_queue.append(snap["total_queue"])
        self.discharged.append(snap["discharged"])
        self.gridlocked.append(bool(snap["gridlocked"]))
        for ev in snap.get("events", []):
            if ev.get("type") in SHOCK_EVENT_TYPES:
                self.shock_ticks.append(snap["tick"])

    def record_decision(self, decision: dict[str, Any]) -> None:
        self.decision_count += 1
        if decision.get("failed"):
            self.llm_failures += 1
        if decision.get("backend_ms") is not None:
            self.backend_ms.append(float(decision["backend_ms"]))
        for r in decision.get("rejected", []):
            reason = r.get("reason", "unknown")
            self.rejected_by_reason[reason] = self.rejected_by_reason.get(reason, 0) + 1
            self.rejected_total += 1
        usage = decision.get("usage") or {}
        self.usage_in += usage.get("input_tokens", 0)
        self.usage_out += usage.get("output_tokens", 0)
        self.usage_cache_read += usage.get("cache_read_input_tokens", 0)

    # ------------------------------------------------------------------
    def _recovery(self) -> dict[str, Any]:
        """For each shock onset, baseline = median pre-shock queue; recovery =
        ticks until queue falls back within 1.2x baseline. Unrecovered shocks
        (queue never settles before the run ends) are counted separately."""
        if not self.total_queue:
            return {"shocks": 0, "mean_recovery_ticks": None,
                    "unrecovered_shocks": 0, "peak_queue": 0}
        # dedupe consecutive onsets within a short window into one shock
        onsets: list[int] = []
        for t in sorted(set(self.shock_ticks)):
            if not onsets or t - onsets[-1] > 5:
                onsets.append(t)

        idx = {t: i for i, t in enumerate(self.ticks)}
        recoveries: list[int] = []
        unrecovered = 0
        for t0 in onsets:
            i0 = idx.get(t0)
            if i0 is None:
                continue
            pre = self.total_queue[max(0, i0 - 20):i0] or [self.total_queue[i0]]
            baseline = statistics.median(pre)
            target = max(baseline * 1.2, baseline + 2)
            rec: Optional[int] = None
            for j in range(i0 + 1, len(self.total_queue)):
                if self.total_queue[j] <= target:
                    rec = self.ticks[j] - t0
                    break
            if rec is None:
                unrecovered += 1
            else:
                recoveries.append(rec)
        return {
            "shocks": len(onsets),
            "mean_recovery_ticks": round(statistics.mean(recoveries), 1) if recoveries else None,
            "unrecovered_shocks": unrecovered,
            "peak_queue": max(self.total_queue) if self.total_queue else 0,
        }

    def finalize(self, sim) -> dict[str, Any]:
        n_ticks = len(self.ticks) or 1
        gridlock_ticks = sum(self.gridlocked)
        competence = {
            "arrived": sim.arrived_total,
            "throughput_per_tick": round(sim.arrived_total / n_ticks, 3),
            "mean_travel": round(statistics.mean(sim.travel_times), 2) if sim.travel_times else None,
            "p95_travel": _percentile(sim.travel_times, 95),
            "mean_wait": round(statistics.mean(sim.wait_times), 2) if sim.wait_times else None,
            "mean_queue": round(statistics.mean(self.total_queue), 2) if self.total_queue else 0,
        }
        safety = {
            "rejected_total": self.rejected_total,
            "by_reason": dict(sorted(self.rejected_by_reason.items())),
            "gridlock_ticks": gridlock_ticks,
            "gridlock_fraction": round(gridlock_ticks / n_ticks, 3),
        }
        decisions = {
            "count": self.decision_count,
            "llm_failures": self.llm_failures,
            "mean_backend_ms": round(statistics.mean(self.backend_ms), 1) if self.backend_ms else None,
            "tokens_in": self.usage_in,
            "tokens_out": self.usage_out,
            "tokens_cache_read": self.usage_cache_read,
        }
        return {
            "competence": competence,
            "safety": safety,
            "robustness": self._recovery(),
            "decisions": decisions,
            "totals": {"ticks": len(self.ticks), "spawned": sim.spawned_total},
        }
