"""The run loop that ties simulator + controller + metrics + logging together.

Kept out of the CLI so it is unit-testable and reusable.
"""

from __future__ import annotations

from typing import Any, Optional

from .config import RunConfig
from .controllers import make_controller
from .grid import seg_key
from .logging_io import RunWriter
from .metrics import MetricsCollector
from .simulation import Simulator


def _serialize_action(a: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"action": a["action"]}
    if "node" in a:
        out["node"] = f"{a['node'][0]},{a['node'][1]}"
    if "pair" in a:
        out["pair"] = list(a["pair"])
    if "seg" in a:
        out["seg"] = seg_key(*a["seg"])
    if "avoid" in a:
        out["avoid"] = [seg_key(*s) for s in a["avoid"]]
    if "text" in a:
        out["text"] = a["text"]
    return out


def run_single(cfg: RunConfig, log_path: Optional[str] = None,
               controller=None) -> dict[str, Any]:
    """Run one (controller, seed) episode. Returns the scorecard; optionally
    writes the full per-tick JSONL to ``log_path``."""
    sim = Simulator(cfg)
    if controller is None:
        controller = make_controller(cfg.controller, backend=cfg.backend,
                                     model=cfg.model, effort=cfg.effort)
    metrics = MetricsCollector()
    writer = RunWriter(log_path, meta={"config": cfg.asdict()}) if log_path else None

    try:
        for t in range(cfg.sim.ticks):
            decision: Optional[dict[str, Any]] = None
            if t % cfg.sim.decision_interval == 0:
                raw, meta = controller.decide(sim)
                accepted, rejected = sim.apply_actions(raw)
                # supervised controller validates its own signal directives;
                # fold those rejections into the safety record too.
                rejected = rejected + meta.get("controller_rejected", [])
                metrics.record_decision({"rejected": rejected,
                                         "backend_ms": meta.get("backend_ms"),
                                         "failed": meta.get("failed", False),
                                         "usage": meta.get("usage", {})})
                decision = {
                    "submitted": raw,
                    "accepted": [_serialize_action(a) for a in accepted],
                    "rejected": rejected,
                    "directives": meta.get("directives", []),  # supervised bias/pin
                    "backend_ms": meta.get("backend_ms"),
                    "failed": meta.get("failed", False),
                    "usage": meta.get("usage", {}),
                }
            fired = sim.step_tick()
            snap = sim.snapshot(fired)
            metrics.update_tick(snap)
            if writer:
                writer.write_tick(snap, decision)

        scorecard = metrics.finalize(sim)
        if writer:
            writer.write_scorecard(scorecard)
    finally:
        if writer:
            writer.close()
    return scorecard
