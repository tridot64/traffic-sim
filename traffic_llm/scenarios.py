"""Scenario presets: the four control modes the experiment compares, plus a
couple of scripted stress scenarios for reproducible regression/safety tests.
"""

from __future__ import annotations

from .config import CONTROL_MODES, ScenarioConfig


def _base(control_mode: str, **overrides) -> ScenarioConfig:
    assert control_mode in CONTROL_MODES, control_mode
    params = {"name": control_mode, "control_mode": control_mode}
    params.update(overrides)
    return ScenarioConfig(**params)


# One preset per control mode (moderate random shocks so robustness is exercised).
SCENARIOS: dict[str, ScenarioConfig] = {
    "signals": _base("signals"),
    "routing": _base("routing"),
    "both": _base("both"),
    "dispatcher": _base("dispatcher"),
    # Calm variant: no random shocks — isolates baseline competence.
    "both_calm": _base("both", name="both_calm", shock_closure_rate=0.0,
                        shock_surge_rate=0.0),
    # Destination hotspots: two corners that attract disproportionate trips,
    # and the dominant one shifts partway through the run ("on a given time").
    # The controller should read the hotspot/inflow signal and route around the
    # congestion building toward them. Nodes 0,3 / 3,0 are valid on 4x4+ grids.
    "both_hotspots": _base(
        "both", name="both_hotspots", shock_closure_rate=0.0, shock_surge_rate=0.0,
        hotspots=(
            {"node": "0,3", "weight": 7, "start": 0, "end": 120},
            {"node": "3,0", "weight": 7, "start": 90, "end": 100000},
        ),
    ),
    "dispatcher_hotspots": _base(
        "dispatcher", name="dispatcher_hotspots",
        shock_closure_rate=0.002, shock_surge_rate=0.0,
        hotspots=(
            {"node": "0,3", "weight": 7, "start": 0, "end": 120},
            {"node": "3,0", "weight": 7, "start": 90, "end": 100000},
        ),
    ),
    # Reproducible stress: a scripted closure + surge hitting the network at
    # fixed ticks. Used by tests and for apples-to-apples robustness demos.
    "dispatcher_stress": _base(
        "dispatcher", name="dispatcher_stress",
        shock_closure_rate=0.0, shock_surge_rate=0.0,
        scripted_events=(
            {"type": "closure", "seg": "2,1->2,2", "tick": 40, "duration": 60},
            {"type": "surge", "tick": 80, "duration": 40, "multiplier": 3.0},
        ),
    ),
}


def get_scenario(name: str) -> ScenarioConfig:
    if name not in SCENARIOS:
        raise KeyError(f"unknown scenario '{name}'. options: {sorted(SCENARIOS)}")
    return SCENARIOS[name]
