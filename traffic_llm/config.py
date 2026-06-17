"""Configuration dataclasses for the simulation and experiments.

Everything that affects a run is captured here so a run is fully reproducible
from (RunConfig + seed). No global state, no wall-clock, no env reads here.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True)
class GridConfig:
    """Topology of the road network: an ``rows x cols`` lattice of intersections
    connected by bidirectional road segments."""

    rows: int = 5
    cols: int = 5
    cells_per_segment: int = 12        # default CA cells per road segment
    vmax: int = 3                      # default max car speed in cells/tick (speed limit)
    # per-road speed-limit / length overrides on the generated lattice, e.g.
    # {"seg": "0,0->0,1", "vmax": 5} or {"seg": "...", "vmax": 1, "cells": 8}.
    speed_limits: tuple = ()

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MapConfig:
    """A custom road map: an explicit set of directed roads between integer
    lattice cells (nodes must stay on the grid so NEMA headings are valid, but
    you choose which roads exist, their direction, speed limit, and length).
    Each road is {"from":"r,c","to":"r,c","vmax":N?,"cells":N?}."""

    roads: tuple = ()
    default_vmax: int = 3
    default_cells: int = 12

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SimConfig:
    """Dynamics: how long to run, how often the controller decides, and the
    statistical knobs for demand and driver behavior."""

    ticks: int = 500
    decision_interval: int = 10        # ticks between controller decisions
    demand_rate: float = 4.0           # expected new cars spawned per tick (Poisson-ish)
    aggressiveness_mean: float = 0.5   # driver gap-acceptance / dawdle tendency
    aggressiveness_std: float = 0.2
    p_slow: float = 0.25               # base Nagel-Schreckenberg dawdle probability

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SignalConfig:
    """NEMA signal timing (ticks). Clearance = yellow then all-red between
    phase-pair changes; min_green locks a phase in, max_green forces gap-out."""

    min_green: int = 6
    max_green: int = 40
    yellow: int = 3
    all_red: int = 2

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


# The four control modes the user asked for, expressed as the set of action
# types a controller is permitted to emit in that scenario.
CONTROL_MODES: dict[str, tuple[str, ...]] = {
    "signals": ("call_phase",),
    "routing": ("reroute",),
    "both": ("call_phase", "reroute"),
    "dispatcher": ("call_phase", "reroute", "close_road", "open_road", "advisory"),
}


@dataclass(frozen=True)
class ScenarioConfig:
    """A named scenario = a control mode + a shock profile.

    ``shock_*`` parameters seed the EventScheduler; ``scripted_events`` are
    reproducible stress events injected at fixed ticks (used for regression and
    safety tests). See ``scenarios.py`` for presets.
    """

    name: str = "both"
    control_mode: str = "both"
    shock_closure_rate: float = 0.004  # prob per segment per tick of a random closure
    closure_duration: int = 40         # ticks a random closure lasts
    shock_surge_rate: float = 0.01     # prob per tick of a demand surge starting
    surge_multiplier: float = 3.0      # demand multiplier during a surge
    surge_duration: int = 30
    scripted_events: tuple = ()        # tuple of event dicts, see events.py
    # Destination hotspots: nodes that attract disproportionate trips, optionally
    # only within a time window. Each is {"node":"r,c","weight":w,"start":t,"end":t}.
    # A car picks its destination with probability ∝ (1 + sum of active weights).
    hotspots: tuple = ()

    @property
    def allowed_actions(self) -> tuple[str, ...]:
        return CONTROL_MODES[self.control_mode]

    def asdict(self) -> dict[str, Any]:
        d = asdict(self)
        d["allowed_actions"] = list(self.allowed_actions)
        return d


@dataclass(frozen=True)
class RunConfig:
    """A complete, reproducible experiment specification for one (controller,
    seed) run."""

    grid: GridConfig = field(default_factory=GridConfig)
    sim: SimConfig = field(default_factory=SimConfig)
    signal: SignalConfig = field(default_factory=SignalConfig)
    scenario: ScenarioConfig = field(default_factory=ScenarioConfig)
    road_map: "MapConfig | None" = None  # if set, overrides the generated grid
    controller: str = "actuated"       # llm | actuated | fixed | maxpressure | donothing
    backend: str = "mock"              # claude | mock  (only used when controller == llm)
    model: str = "claude-opus-4-8"
    effort: str = "medium"
    seed: int = 0

    def asdict(self) -> dict[str, Any]:
        return {
            "grid": self.grid.asdict(),
            "sim": self.sim.asdict(),
            "signal": self.signal.asdict(),
            "scenario": self.scenario.asdict(),
            "road_map": self.road_map.asdict() if self.road_map else None,
            "controller": self.controller,
            "backend": self.backend,
            "model": self.model,
            "effort": self.effort,
            "seed": self.seed,
        }
