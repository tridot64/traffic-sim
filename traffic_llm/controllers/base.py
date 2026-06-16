"""Controller interface.

A controller is handed the live ``Simulator`` at each decision step and returns
``(raw_actions, meta)``. Baselines read sim state directly (white-box); the LLM
controller only reads ``sim.observation()`` and calls its backend. The run loop
validates and applies the returned actions via ``sim.apply_actions``.
"""

from __future__ import annotations

from typing import Any, Protocol


class Controller(Protocol):
    name: str

    def decide(self, sim) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        ...
