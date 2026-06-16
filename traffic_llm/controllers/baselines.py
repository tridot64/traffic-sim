"""Baseline controllers for the NEMA micro engine — the references the LLM is
measured against.

- DoNothing:   never calls a phase (signals sit on their startup pair).
- Fixed:       cycles phase pairs on a fixed schedule (fixed-time control).
- Actuated:    the "pressure-plate" controller — hold the current phase while it
               has waiting cars, otherwise switch to the heaviest-demand phase;
               when every phase is loaded, fall back to a timed cycle. This is
               vehicle-actuated control, the standard real-world adaptive signal.
- MaxPressure: greedy max-pressure — serve the phase with the most waiting cars.
"""

from __future__ import annotations

from typing import Any

_EMPTY: dict[str, Any] = {}


def _worst_jam_action(sim, allowed) -> list[dict[str, Any]]:
    if "advisory" not in allowed and "reroute" not in allowed:
        return []
    worst, worst_load = None, 0.7
    for seg, lane in sim.lanes.items():
        if sim.net.segments[seg].closed:
            continue
        load = sum(1 for c in lane.cells if c is not None) / lane.length
        if load > worst_load:
            worst, worst_load = seg, load
    if worst is None or sim.net.shortest_path(worst[0], worst[1], avoid={worst}) is None:
        return []
    key = f"{worst[0][0]},{worst[0][1]}->{worst[1][0]},{worst[1][1]}"
    if "advisory" in allowed:
        return [{"action": "advisory", "text": f"jam on {key}", "avoid": [key]}]
    return [{"action": "reroute", "node": f"{worst[0][0]},{worst[0][1]}", "avoid": [key]}]


def _call(node, pair) -> dict[str, Any]:
    return {"action": "call_phase", "node": f"{node[0]},{node[1]}", "pair": list(pair)}


def actuated_choice(sig, pressures: dict, max_green: int):
    """Vehicle-actuated phase selection: extend the heaviest phase while it leads
    and is under max-green; at max-green, MAX-OUT — force a switch to a waiting
    conflicting phase so it can never starve. (Shared by the actuated baseline
    and the supervised hybrid.)"""
    active = sig.active_pair
    if not pressures:
        return active
    order = {p: i for i, p in enumerate(sig.valid_pairs)}
    heaviest = max(pressures, key=lambda p: (pressures[p], -order.get(p, 0)))
    active_p = pressures.get(active, 0)
    if sig.time_in_pair >= max_green:
        others = {p: v for p, v in pressures.items() if p != active and v > 0}
        if others:                       # max-out: yield to a waiting approach
            return max(others, key=lambda p: (others[p], -order.get(p, 0)))
        return active                    # nobody else waiting — keep serving
    if active_p > 0 and active_p >= pressures[heaviest]:
        return active                    # extend the current (heaviest) phase
    return heaviest                      # switch to the heaviest demand


class DoNothingController:
    name = "donothing"

    def decide(self, sim):
        return [], _EMPTY


class FixedController:
    name = "fixed"

    def __init__(self) -> None:
        self._idx = 0

    def decide(self, sim):
        allowed = sim.cfg.scenario.allowed_actions
        actions: list[dict[str, Any]] = []
        if "call_phase" in allowed:
            for node, sig in sim.signals.items():
                vp = sig.valid_pairs
                actions.append(_call(node, vp[self._idx % len(vp)]))
            self._idx += 1
        return actions, _EMPTY


class ActuatedController:
    name = "actuated"

    def decide(self, sim):
        allowed = sim.cfg.scenario.allowed_actions
        actions: list[dict[str, Any]] = []
        if "call_phase" in allowed:
            mg = sim.cfg.signal.max_green
            for node, sig in sim.signals.items():
                target = actuated_choice(sig, sim.pair_pressure(node), mg)
                actions.append(_call(node, target))
        actions.extend(_worst_jam_action(sim, allowed))
        return actions, _EMPTY


class MaxPressureController:
    name = "maxpressure"

    def decide(self, sim):
        allowed = sim.cfg.scenario.allowed_actions
        actions: list[dict[str, Any]] = []
        if "call_phase" in allowed:
            for node, sig in sim.signals.items():
                pressures = sim.pair_pressure(node)
                if pressures:
                    target = max(pressures, key=lambda p: (pressures[p], -sig.valid_pairs.index(p)))
                    actions.append(_call(node, target))
        actions.extend(_worst_jam_action(sim, allowed))
        return actions, _EMPTY
