"""Seeded event stream: random + scripted road closures and demand surges.

These are the "surprises" the controller must cope with. Everything derives
from the run's seeded RNG so a scenario is reproducible across controllers,
which is essential for a fair comparison.

The scheduler owns *event-induced* closures only (``Segment.closed_event``);
operator/LLM closures live on ``Segment.closed_operator`` and are applied by
``actions.py``.
"""

from __future__ import annotations

import random
from typing import Any

from .config import ScenarioConfig
from .grid import RoadNetwork, SegId, parse_seg_key, seg_key


class EventScheduler:
    def __init__(self, network: RoadNetwork, scenario: ScenarioConfig, rng: random.Random):
        self.net = network
        self.scn = scenario
        self.rng = rng
        self._closure_expiry: dict[SegId, int] = {}
        self._surge_until: int = -1
        self._surge_multiplier: float = 1.0
        self._scripted: dict[int, list[dict[str, Any]]] = {}
        for ev in scenario.scripted_events:
            self._scripted.setdefault(int(ev["tick"]), []).append(dict(ev))

    @property
    def demand_multiplier(self) -> float:
        return self._surge_multiplier

    def active_closures(self) -> list[str]:
        return [seg_key(*s) for s in self._closure_expiry]

    def step(self, tick: int) -> list[dict[str, Any]]:
        """Advance the event stream by one tick. Mutates segment closures and
        the active demand multiplier; returns the events that fired this tick
        (for the per-tick log)."""
        fired: list[dict[str, Any]] = []

        # 1. expire finished closures / surge
        for seg in [s for s, exp in self._closure_expiry.items() if exp <= tick]:
            self.net.segments[seg].closed_event = False
            del self._closure_expiry[seg]
            fired.append({"type": "reopen", "seg": seg_key(*seg), "tick": tick})
        if self._surge_until <= tick and self._surge_multiplier != 1.0:
            self._surge_multiplier = 1.0
            fired.append({"type": "surge_end", "tick": tick})

        # 2. scripted events for this tick
        for ev in self._scripted.get(tick, []):
            fired.extend(self._apply(ev, tick))

        # 3. random closures (per segment per tick)
        if self.scn.shock_closure_rate > 0:
            for seg, segment in self.net.segments.items():
                if segment.closed:
                    continue
                if self.rng.random() < self.scn.shock_closure_rate:
                    segment.closed_event = True
                    self._closure_expiry[seg] = tick + self.scn.closure_duration
                    fired.append(
                        {"type": "closure", "seg": seg_key(*seg), "tick": tick,
                         "until": tick + self.scn.closure_duration}
                    )

        # 4. random demand surge
        if self._surge_multiplier == 1.0 and self.rng.random() < self.scn.shock_surge_rate:
            self._surge_multiplier = self.scn.surge_multiplier
            self._surge_until = tick + self.scn.surge_duration
            fired.append(
                {"type": "surge", "tick": tick, "until": self._surge_until,
                 "multiplier": self.scn.surge_multiplier}
            )

        return fired

    def _apply(self, ev: dict[str, Any], tick: int) -> list[dict[str, Any]]:
        kind = ev["type"]
        if kind == "closure":
            seg = parse_seg_key(ev["seg"])
            if seg in self.net.segments:
                self.net.segments[seg].closed_event = True
                self._closure_expiry[seg] = tick + int(ev.get("duration", self.scn.closure_duration))
                return [{"type": "closure", "seg": ev["seg"], "tick": tick,
                         "until": self._closure_expiry[seg], "scripted": True}]
        elif kind == "surge":
            self._surge_multiplier = float(ev.get("multiplier", self.scn.surge_multiplier))
            self._surge_until = tick + int(ev.get("duration", self.scn.surge_duration))
            return [{"type": "surge", "tick": tick, "until": self._surge_until,
                     "multiplier": self._surge_multiplier, "scripted": True}]
        return []
