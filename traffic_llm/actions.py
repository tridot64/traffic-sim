"""Controller action types, their JSON tool schemas, and their validation.

Validation is the safety boundary around the controller. The signal action is a
NEMA *phase-pair call* (``call_phase``): the controller names a compatible
ring-barrier pair, and the intersection's signal handles clearance and min-green
itself. Calling an incompatible (conflicting) pair is rejected — the
microscopic analogue of a conflicting-green violation. Routing/closure actions
are rejected if they would isolate an intersection.
"""

from __future__ import annotations

from typing import Any, Optional

from .grid import RoadNetwork, SegId, parse_seg_key
from .micro.movements import COMPATIBLE_PAIRS


def tool_schemas(allowed: tuple[str, ...]) -> list[dict[str, Any]]:
    node = {"type": "string", "description": "intersection id 'row,col', e.g. '2,3'"}
    seg = {"type": "string", "description": "segment id 'r,c->r,c' (from->to)"}
    pairs_str = ", ".join(f"[{a},{b}]" for a, b in COMPATIBLE_PAIRS)
    schemas = {
        "call_phase": {
            "name": "call_phase",
            "description": "Call a NEMA phase pair to serve at an intersection. "
            f"Only these conflict-free pairs are valid: {pairs_str}. Any other "
            "pair is rejected as a conflicting-phase safety violation. The signal "
            "applies yellow/all-red clearance and min-green automatically.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "node": node,
                    "pair": {"type": "array", "items": {"type": "integer"},
                             "minItems": 2, "maxItems": 2,
                             "description": "[ring1_phase, ring2_phase]"},
                },
                "required": ["node", "pair"],
                "additionalProperties": False,
            },
        },
        "reroute": {
            "name": "reroute",
            "description": "Advise cars discharging at a node to avoid segments. "
            "Rejected if it would isolate a node.",
            "input_schema": {
                "type": "object",
                "properties": {"node": node, "avoid": {"type": "array", "items": seg}},
                "required": ["node", "avoid"], "additionalProperties": False,
            },
        },
        "close_road": {
            "name": "close_road",
            "description": "Operator-close a segment. Rejected if it would isolate a node.",
            "input_schema": {
                "type": "object", "properties": {"seg": seg},
                "required": ["seg"], "additionalProperties": False,
            },
        },
        "open_road": {
            "name": "open_road",
            "description": "Reopen an operator-closed segment.",
            "input_schema": {
                "type": "object", "properties": {"seg": seg},
                "required": ["seg"], "additionalProperties": False,
            },
        },
        "advisory": {
            "name": "advisory",
            "description": "Broadcast a soft network-wide avoid advisory with a note.",
            "input_schema": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "avoid": {"type": "array", "items": seg}},
                "required": ["text", "avoid"], "additionalProperties": False,
            },
        },
    }
    return [schemas[a] for a in allowed if a in schemas]


def _node(s: str) -> tuple[int, int]:
    r, c = s.split(",")
    return (int(r), int(c))


def _connectivity_ok(net: RoadNetwork, removed: set[SegId]) -> bool:
    for (frm, to) in removed:
        if net.shortest_path(frm, to, avoid=removed) is None:
            return False
    return True


def validate(net: RoadNetwork, raw_actions: list[dict[str, Any]],
             allowed: tuple[str, ...], signals: Optional[dict] = None):
    """Split raw actions into (accepted, rejected). ``signals`` maps node ->
    IntersectionSignal (needed to check phase-call validity)."""
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    signals = signals or {}

    def reject(a, reason):
        rejected.append({**a, "reason": reason})

    for a in raw_actions:
        kind = a.get("action")
        if kind not in allowed:
            reject(a, "action_not_allowed")
            continue
        try:
            if kind == "call_phase":
                _validate_phase(signals, a, accepted, reject)
            elif kind == "reroute":
                _validate_avoid(net, a, "node", accepted, reject)
            elif kind == "advisory":
                _validate_avoid(net, a, None, accepted, reject)
            elif kind == "close_road":
                _validate_close(net, a, accepted, reject)
            elif kind == "open_road":
                _validate_open(net, a, accepted, reject)
            else:
                reject(a, "unknown_action")
        except (KeyError, ValueError, TypeError) as exc:
            reject(a, f"malformed:{type(exc).__name__}")

    return accepted, rejected


def _validate_phase(signals, a, accepted, reject) -> None:
    node = _node(a["node"])
    if node not in signals:
        reject(a, "no_such_node")
        return
    pair = tuple(int(x) for x in a["pair"])
    if len(pair) != 2 or pair not in COMPATIBLE_PAIRS:
        reject(a, "incompatible_phase")
        return
    if pair not in signals[node].valid_pairs:
        reject(a, "phase_not_at_node")   # compatible, but serves no movement here
        return
    accepted.append({"action": "call_phase", "node": node, "pair": pair})


def _validate_avoid(net, a, node_key, accepted, reject) -> None:
    segs: set[SegId] = set()
    for s in a.get("avoid", []):
        seg = parse_seg_key(s)
        if seg not in net.segments:
            reject(a, "no_such_segment")
            return
        segs.add(seg)
    if segs and not _connectivity_ok(net, segs):
        reject(a, "isolates_node")
        return
    out: dict[str, Any] = {"action": a["action"], "avoid": segs}
    if node_key:
        node = _node(a[node_key])
        if node not in net._adj:
            reject(a, "no_such_node")
            return
        out["node"] = node
    if a["action"] == "advisory":
        out["text"] = str(a.get("text", ""))
    accepted.append(out)


def _validate_close(net, a, accepted, reject) -> None:
    seg = parse_seg_key(a["seg"])
    if seg not in net.segments:
        reject(a, "no_such_segment")
        return
    if net.segments[seg].closed:
        reject(a, "already_closed")
        return
    if not _connectivity_ok(net, {seg}):
        reject(a, "isolates_node")
        return
    accepted.append({"action": "close_road", "seg": seg})


def _validate_open(net, a, accepted, reject) -> None:
    seg = parse_seg_key(a["seg"])
    if seg not in net.segments:
        reject(a, "no_such_segment")
        return
    if not net.segments[seg].closed_operator:
        reject(a, "not_operator_closed")
        return
    accepted.append({"action": "open_road", "seg": seg})
