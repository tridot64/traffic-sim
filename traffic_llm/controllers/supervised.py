"""Supervised hybrid controller: a robust actuated algorithm with an LLM on top.

The base layer is the vehicle-actuated NEMA controller (the same
``actuated_choice`` the actuated baseline uses) — it runs every decision and, on
its own, behaves exactly like the actuated baseline. Periodically the LLM
*supervises* it: it reads the actuator pressures, the live NEMA phase/state at
each intersection, and the destination hotspots, then issues high-level
directives that tune the algorithm:

  - ``bias_phase(node, pair, weight)``  — nudge: add demand weight to a phase so
    the actuated logic favors it (e.g. open up the corridor toward a hotspot).
  - ``pin_phase(node, pair, ticks)``    — strongarm: force a phase at a node for a
    window, overriding the algorithm (e.g. set up a green wave / pre-empt).

plus any routing/closure actions the scenario allows. With no directives (or a
mock backend) the controller is pure actuated. The LLM is a slow policy layer,
not a per-tick operator — which is what it is actually good at.
"""

from __future__ import annotations

from typing import Any, Optional

from ..prompts import build_supervisor_system_prompt, supervisor_tool_schemas
from .baselines import _call, _worst_jam_action, actuated_choice

_EMPTY: dict[str, Any] = {}
_SIGNAL_DIRECTIVES = {"bias_phase", "pin_phase"}
_SIM_ACTIONS = {"reroute", "advisory", "close_road", "open_road"}
BIAS_CLAMP = 25.0
MAX_PIN_TICKS = 60


def _node(s) -> tuple[int, int]:
    r, c = s.split(",")
    return (int(r), int(c))


class SupervisedActuatedController:
    name = "supervised"

    def __init__(self, backend=None, llm_interval: int = 4):
        self.backend = backend
        self.llm_interval = llm_interval
        self.bias: dict[tuple, dict[tuple, float]] = {}
        self.pins: dict[tuple, tuple[tuple, int]] = {}
        self._decisions = 0
        self._last_meta: dict[str, Any] = {}

    # ------------------------------------------------------------------
    def _supervisor_allowed(self, scenario_allowed) -> tuple[str, ...]:
        routing = tuple(a for a in scenario_allowed if a in _SIM_ACTIONS)
        return ("bias_phase", "pin_phase") + routing

    def decide(self, sim):
        actions: list[dict[str, Any]] = []
        meta: dict[str, Any] = _EMPTY

        consult = self.backend is not None and self._decisions % self.llm_interval == 0
        if consult:
            actions += self._consult_llm(sim)
            meta = self._last_meta

        actions += self._actuated_with_policy(sim)
        # Base behaves EXACTLY like the actuated baseline (incl. its worst-jam
        # routing) so that a null supervisor == actuated in every scenario; the
        # LLM's bias/pin/reroute are the only delta.
        actions += _worst_jam_action(sim, sim.cfg.scenario.allowed_actions)
        self._decisions += 1
        return actions, meta

    # ------------------------------------------------------------------
    def _consult_llm(self, sim) -> list[dict[str, Any]]:
        sup_allowed = self._supervisor_allowed(sim.cfg.scenario.allowed_actions)
        obs = {**sim.observation(), "allowed_actions": list(sup_allowed)}
        system = build_supervisor_system_prompt(sup_allowed)
        schemas = supervisor_tool_schemas(sup_allowed)
        raw, meta = self.backend.decide(system, obs, schemas)

        self.bias = {}                       # each consultation sets a fresh policy
        forwarded: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        applied: list[dict[str, Any]] = []   # accepted signal directives (for the log)
        for a in raw:
            act = a.get("action")
            if act == "bias_phase":
                self._apply_bias(sim, a, applied, rejected)
            elif act == "pin_phase":
                self._apply_pin(sim, a, applied, rejected)
            elif act in _SIM_ACTIONS:
                forwarded.append(a)          # validated later by sim.apply_actions
            else:
                rejected.append({**a, "reason": "unknown_directive"})
        self._last_meta = {
            "backend_ms": meta.get("backend_ms"),
            "failed": meta.get("failed", False),
            "usage": meta.get("usage", {}),
            "controller_rejected": rejected,
            "directives": applied,           # so the log shows what the LLM tuned
        }
        return forwarded

    def _apply_bias(self, sim, a, applied, rejected) -> None:
        try:
            node = _node(a["node"]); pair = tuple(int(x) for x in a["pair"])
            weight = float(a["weight"])
        except (KeyError, ValueError, TypeError):
            rejected.append({**a, "reason": "malformed"}); return
        if node not in sim.signals or pair not in sim.signals[node].valid_pairs:
            rejected.append({**a, "reason": "bad_bias_target"}); return
        weight = max(-BIAS_CLAMP, min(BIAS_CLAMP, weight))
        self.bias.setdefault(node, {})[pair] = weight
        applied.append({"action": "bias_phase", "node": a["node"], "pair": list(pair),
                        "weight": weight})

    def _apply_pin(self, sim, a, applied, rejected) -> None:
        try:
            node = _node(a["node"]); pair = tuple(int(x) for x in a["pair"])
            ticks = int(a.get("ticks", 20))
        except (KeyError, ValueError, TypeError):
            rejected.append({**a, "reason": "malformed"}); return
        if node not in sim.signals or pair not in sim.signals[node].valid_pairs:
            rejected.append({**a, "reason": "bad_pin_target"}); return
        ticks = max(1, min(MAX_PIN_TICKS, ticks))
        self.pins[node] = (pair, sim.tick + ticks)
        applied.append({"action": "pin_phase", "node": a["node"], "pair": list(pair),
                        "ticks": ticks})

    # ------------------------------------------------------------------
    def _actuated_with_policy(self, sim) -> list[dict[str, Any]]:
        mg = sim.cfg.signal.max_green
        out: list[dict[str, Any]] = []
        for node, sig in sim.signals.items():
            pin = self.pins.get(node)
            if pin is not None:
                pair, expiry = pin
                if sim.tick < expiry and pair in sig.valid_pairs:
                    out.append(_call(node, pair))   # strongarm override
                    continue
                del self.pins[node]
            pressures = dict(sim.pair_pressure(node))
            for p, w in self.bias.get(node, {}).items():   # LLM nudge
                pressures[p] = pressures.get(p, 0) + w
            out.append(_call(node, actuated_choice(sig, pressures, mg)))
        return out
