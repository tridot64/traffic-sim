"""Per-intersection NEMA signal: a dual-ring controller with a green → yellow →
all-red clearance state machine and a min-green lock.

The *policy* (which phase pair to serve next) is supplied by the experiment
controller via :meth:`request_pair`; this class enforces the safety mechanics —
you cannot snap between pairs without clearance, and a pair holds for at least
``min_green`` ticks.
"""

from __future__ import annotations

from .movements import COMPATIBLE_PAIRS, pair_movements


class IntersectionSignal:
    def __init__(self, node, existing_movements: set[tuple[str, str]], cfg):
        self.node = node
        self.existing = existing_movements
        self.cfg = cfg
        # valid pairs = compatible pairs that serve at least one real movement
        self.valid_pairs: list[tuple[int, int]] = [
            p for p in COMPATIBLE_PAIRS if pair_movements(p) & self.existing
        ]
        self.active_pair: tuple[int, int] = self.valid_pairs[0]
        self.target_pair = self.active_pair
        self.state = "green"            # green | yellow | allred
        self.timer = 0                  # ticks in current state
        self.time_in_pair = 0           # ticks since the active pair last went green

    # ---- queried by the engine each tick ----
    def is_green(self) -> bool:
        return self.state == "green"

    def protected_movements(self) -> set[tuple[str, str]]:
        """Movements that may discharge now. During yellow the active pair is
        still clearing; during all-red nothing moves (protected)."""
        if self.state in ("green", "yellow"):
            return pair_movements(self.active_pair) & self.existing
        return set()

    # ---- policy input ----
    def request_pair(self, pair: tuple[int, int]) -> None:
        """Controller asks to serve ``pair`` next. Honored only at the next safe
        boundary: ignored until min-green elapses, then triggers clearance."""
        if pair in self.valid_pairs:
            self.target_pair = pair

    # ---- mechanism: advance one tick ----
    def step(self) -> None:
        self.timer += 1
        if self.state == "green":
            self.time_in_pair += 1
            switching = self.target_pair != self.active_pair
            maxed = self.time_in_pair >= self.cfg.max_green
            if (switching or maxed) and self.time_in_pair >= self.cfg.min_green:
                if not switching and maxed:
                    # forced gap-out with no pending target: hold (controller will
                    # pick next); nothing to clear to, so just reset the counter.
                    self.time_in_pair = 0
                else:
                    self.state, self.timer = "yellow", 0
        elif self.state == "yellow":
            if self.timer >= self.cfg.yellow:
                self.state, self.timer = "allred", 0
        elif self.state == "allred":
            if self.timer >= self.cfg.all_red:
                self.active_pair = self.target_pair
                self.state, self.timer, self.time_in_pair = "green", 0, 0
