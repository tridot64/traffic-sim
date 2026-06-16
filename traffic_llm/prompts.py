"""Prompt construction shared by the LLM controller and the Claude backend.

(The LLM path is currently on hold while the micro engine is validated, but is
kept in sync so it stays runnable.)
"""

from __future__ import annotations

from typing import Any

from .micro.movements import COMPATIBLE_PAIRS

_ACTION_HELP = {
    "call_phase": "call_phase(node, [p1,p2]) — serve a NEMA phase pair at an intersection.",
    "reroute": "reroute(node, avoid[]) — divert cars discharging at a node away from segments.",
    "close_road": "close_road(seg) — operator-close a segment.",
    "open_road": "open_road(seg) — reopen an operator-closed segment.",
    "advisory": "advisory(text, avoid[]) — broadcast a soft network-wide route advisory.",
}


def build_system_prompt(allowed: tuple[str, ...]) -> str:
    tools = "\n".join(f"  - {_ACTION_HELP[a]}" for a in allowed if a in _ACTION_HELP)
    pairs = ", ".join(f"[{a},{b}]" for a, b in COMPATIBLE_PAIRS)
    return (
        "You are the traffic-management operator for a city road grid running a "
        "full NEMA 8-phase signal system. Each decision step you receive a "
        "situation report and may issue control actions.\n\n"
        "Signals are controlled by calling a conflict-free NEMA phase pair; the "
        f"only valid pairs are: {pairs}. The intersection applies yellow/all-red "
        "clearance and a minimum green automatically — you just choose which pair "
        "to serve next.\n\n"
        "Objectives, in priority order:\n"
        "  1. SAFETY — only ever call a valid (conflict-free) phase pair, and "
        "never isolate an intersection.\n"
        "  2. Keep queues and travel times low; serve the approaches with the most "
        "waiting cars.\n"
        "  3. Recover quickly after closures and demand surges.\n\n"
        "You control ONLY these action types this run:\n"
        f"{tools}\n\n"
        "Act decisively to clear the heaviest queues, but emit only valid "
        "actions — invalid or unsafe actions are rejected and count against you."
    )


_SUP_HELP = {
    "bias_phase": "bias_phase(node, [p1,p2], weight) — nudge the algorithm to favor a phase.",
    "pin_phase": "pin_phase(node, [p1,p2], ticks) — strongarm: force a phase for a window.",
    "reroute": "reroute(node, avoid[]) — divert cars discharging at a node.",
    "advisory": "advisory(text, avoid[]) — broadcast a soft network-wide route advisory.",
    "close_road": "close_road(seg) — operator-close a segment.",
    "open_road": "open_road(seg) — reopen an operator-closed segment.",
}


def build_supervisor_system_prompt(allowed: tuple[str, ...]) -> str:
    tools = "\n".join(f"  - {_SUP_HELP[a]}" for a in allowed if a in _SUP_HELP)
    pairs = ", ".join(f"[{a},{b}]" for a, b in COMPATIBLE_PAIRS)
    return (
        "You SUPERVISE a vehicle-actuated NEMA signal algorithm running a road "
        "grid. The algorithm already serves the heaviest approach at each "
        "intersection and switches on gap-out / max-green — by default it runs "
        "itself and you do NOT need to touch most intersections. Your job is to "
        "spot network-level patterns the local algorithm cannot see — especially "
        "destination HOTSPOTS and the congestion building toward them — and tune "
        "the algorithm only where it helps overall flow.\n\n"
        f"Valid NEMA phase pairs: {pairs}.\n\n"
        "Use the lightest tool that works:\n"
        "  - bias_phase to gently favor a corridor (e.g. toward/away from a hotspot);\n"
        "  - pin_phase only to strongarm a key intersection briefly (green wave, "
        "pre-empt a forming jam) — overrides the algorithm, so use sparingly;\n"
        "  - reroute/advisory to steer traffic around hotspots or closures.\n\n"
        "Available tools this run:\n"
        f"{tools}\n\n"
        "Intervene where it improves throughput; leave well-flowing intersections "
        "to the algorithm. Invalid directives are rejected and count against you."
    )


def supervisor_tool_schemas(allowed: tuple[str, ...]) -> list[dict[str, Any]]:
    from .actions import tool_schemas
    node = {"type": "string", "description": "intersection id 'row,col'"}
    pair = {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2,
            "description": "[ring1_phase, ring2_phase] — a valid NEMA pair"}
    schemas = []
    if "bias_phase" in allowed:
        schemas.append({"name": "bias_phase",
            "description": "Nudge the actuated algorithm to favor a phase pair at a "
            "node by adding `weight` extra demand to it (negative to disfavor).",
            "input_schema": {"type": "object", "properties": {
                "node": node, "pair": pair,
                "weight": {"type": "number", "description": "demand bias, ~ -25..25"}},
                "required": ["node", "pair", "weight"], "additionalProperties": False}})
    if "pin_phase" in allowed:
        schemas.append({"name": "pin_phase",
            "description": "Strongarm: force a phase pair at a node for `ticks` ticks, "
            "overriding the algorithm. Use sparingly.",
            "input_schema": {"type": "object", "properties": {
                "node": node, "pair": pair,
                "ticks": {"type": "integer", "description": "hold duration, 1..60"}},
                "required": ["node", "pair", "ticks"], "additionalProperties": False}})
    routing = tuple(a for a in allowed if a in ("reroute", "advisory", "close_road", "open_road"))
    return schemas + tool_schemas(routing)


def render_observation(obs: dict[str, Any]) -> str:
    lines = [
        f"tick={obs['tick']}  active_cars={obs['active_cars']}  "
        f"total_queue={obs['total_queue']}  arrived={obs['arrived_total']}  "
        f"mean_wait={obs['mean_wait']}  demand_x{obs['demand_multiplier']}",
    ]
    if obs["closed_segments"]:
        lines.append("closed: " + ", ".join(obs["closed_segments"]))
    if obs.get("hotspots"):
        hs = ", ".join(f"{h['node']}(inflow {h['inflow']})" for h in obs["hotspots"])
        lines.append("destination HOTSPOTS (heavy trip attractors right now): " + hs
                     + " — expect congestion building toward these; route around it.")
    busy = sorted(obs["nodes"].items(), key=lambda kv: -kv[1]["waiting_total"])[:10]
    busy = [(k, v) for k, v in busy if v["waiting_total"] > 0]
    if busy:
        lines.append("busiest intersections (id | active pair/state | waiting by movement | valid pairs):")
        for k, v in busy:
            wm = " ".join(f"{m}:{c}" for m, c in v["waiting_by_movement"].items())
            vp = " ".join(f"[{p[0]},{p[1]}]" for p in v["valid_pairs"])
            lines.append(f"  {k}  pair[{v['active_pair'][0]},{v['active_pair'][1]}]/"
                         f"{v['state']}  wait[{wm}]  valid:{vp}")
    lines.append("Issue phase calls (and any other allowed actions) to clear the worst queues.")
    return "\n".join(lines)
