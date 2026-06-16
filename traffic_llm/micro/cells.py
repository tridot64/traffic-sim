"""Cellular-automaton lane physics (Nagel-Schreckenberg).

A lane is one directed road segment discretised into cells (index 0 = just past
the upstream intersection, index L-1 = the stop line). At most one car per cell.
Each tick a car accelerates toward ``vmax``, brakes to the gap ahead, randomly
dawdles (less often for aggressive drivers), then advances. The engine owns the
cross-lane coupling (intersection transfers); this module owns within-lane state
and the speed rule.
"""

from __future__ import annotations

import random
from typing import Optional


def p_slow_for(aggressiveness: float, base: float) -> float:
    """Random-dawdle probability. Aggressive drivers (≈1) rarely dawdle; timid
    drivers (≈0) dawdle at the base rate."""
    return max(0.0, min(1.0, base * (1.0 - aggressiveness)))


def ns_new_speed(v: int, gap: int, vmax: int, p_slow: float, rng: random.Random) -> int:
    """One Nagel-Schreckenberg speed update given the free gap ahead (cells)."""
    v = min(v + 1, vmax)          # 1. accelerate
    v = min(v, gap)               # 2. brake to gap
    if v > 0 and rng.random() < p_slow:  # 3. random dawdle
        v -= 1
    return v                       # caller applies 4. move


class Lane:
    """Occupancy grid for one directed segment. Stores car objects by cell."""

    __slots__ = ("length", "cells")

    def __init__(self, length: int):
        self.length = length
        self.cells: list[Optional[object]] = [None] * length

    def free(self, i: int) -> bool:
        return 0 <= i < self.length and self.cells[i] is None

    def at(self, i: int):
        return self.cells[i]

    def place(self, i: int, car) -> None:
        self.cells[i] = car

    def remove(self, i: int) -> None:
        self.cells[i] = None

    def occupied_indices_desc(self) -> list[int]:
        """Cell indices holding a car, front (stop line) first."""
        return [i for i in range(self.length - 1, -1, -1) if self.cells[i] is not None]

    def gap_ahead(self, i: int) -> int:
        """Empty cells between cell ``i`` and the next car ahead, or the stop
        line if none. Used for non-lead and lead-without-clearance cars."""
        for j in range(i + 1, self.length):
            if self.cells[j] is not None:
                return j - i - 1
        return self.length - 1 - i

    def entry_free_run(self) -> int:
        """How many cells from the entry (cell 0) are free — the room available
        to a car crossing in from upstream."""
        run = 0
        for j in range(self.length):
            if self.cells[j] is None:
                run += 1
            else:
                break
        return run
