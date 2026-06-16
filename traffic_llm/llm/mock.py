"""Deterministic, observation-only heuristic standing in for the LLM.

Sees exactly what the model sees (the observation dict + allowed actions) and
emits NEMA phase calls for the heaviest-demand pair at each intersection, plus a
reroute around the worst jam. Lets the harness run with no API key, and is the
template for a future local-model backend.
"""

from __future__ import annotations

from typing import Any

from ..grid import parse_seg_key
from ..micro.movements import pair_movements


class MockBackend:
    name = "mock"

    def decide(self, system_prompt, observation, tool_schemas):
        allowed = set(observation.get("allowed_actions", []))
        actions: list[dict[str, Any]] = []

        if "call_phase" in allowed:
            for node_id, ninfo in observation["nodes"].items():
                wm = ninfo["waiting_by_movement"]
                best, best_press = None, -1
                for p in ninfo["valid_pairs"]:
                    press = sum(wm.get(f"{h}{t}", 0) for (h, t) in pair_movements((p[0], p[1])))
                    if press > best_press:
                        best, best_press = p, press
                if best is not None and best_press > 0 and best != ninfo["active_pair"]:
                    actions.append({"action": "call_phase", "node": node_id, "pair": best})

        if "advisory" in allowed or "reroute" in allowed:
            worst, worst_load = None, 0.8
            for seg, info in observation["lanes"].items():
                if info["closed"] or not info["len"]:
                    continue
                load = info["occ"] / info["len"]
                if load > worst_load:
                    worst, worst_load = seg, load
            if worst is not None:
                if "advisory" in allowed:
                    actions.append({"action": "advisory", "text": f"jam {worst}", "avoid": [worst]})
                else:
                    frm, _ = parse_seg_key(worst)
                    actions.append({"action": "reroute", "node": f"{frm[0]},{frm[1]}", "avoid": [worst]})

        return actions, {"backend_ms": 0.0, "failed": False, "usage": {}}
