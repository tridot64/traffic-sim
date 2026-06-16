"""Per-tick JSONL logging — the audit trail that makes any moment of a run
replayable and edge cases inspectable.

Layout (one JSON object per line):
    line 0:  {"type": "meta",      ...run config...}
    line k:  {"type": "tick",      ...snapshot... , "decision": {...}|null}
    last:    {"type": "scorecard", ...metrics...}
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional


class RunWriter:
    def __init__(self, path: str, meta: dict[str, Any]):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._f = open(path, "w", encoding="utf-8")
        self.path = path
        self._write({"type": "meta", **meta})

    def _write(self, obj: dict[str, Any]) -> None:
        self._f.write(json.dumps(obj, separators=(",", ":")) + "\n")

    def write_tick(self, snap: dict[str, Any], decision: Optional[dict[str, Any]] = None) -> None:
        self._write({"type": "tick", **snap, "decision": decision})

    def write_scorecard(self, scorecard: dict[str, Any]) -> None:
        self._write({"type": "scorecard", **scorecard})

    def close(self) -> None:
        self._f.close()

    def __enter__(self) -> "RunWriter":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def read_run(path: str) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    ticks: list[dict[str, Any]] = []
    scorecard: dict[str, Any] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            kind = obj.get("type")
            if kind == "meta":
                meta = obj
            elif kind == "tick":
                ticks.append(obj)
            elif kind == "scorecard":
                scorecard = obj
    return {"meta": meta, "ticks": ticks, "scorecard": scorecard}
