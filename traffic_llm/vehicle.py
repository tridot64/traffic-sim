"""The Car: an individual vehicle with a route, a destination, and a driver
personality (``aggressiveness``) that affects gap acceptance and the tendency
to self-reroute around closures/jams.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .grid import Node


@dataclass
class Car:
    id: int
    origin: Node
    dest: Node
    born_tick: int
    aggressiveness: float                 # in [0, 1]
    route: list[Node]                     # node sequence including current node
    route_idx: int = 0                    # index of the node the car is currently at/leaving

    # --- mutable motion state ---
    state: str = "queued"                 # queued | traveling | arrived
    seg_remaining: int = 0                # (mesoscopic) ticks left on the segment
    wait_ticks: int = 0                   # ticks spent stopped (v==0) / waiting to enter
    travel_ticks: int = 0                 # total ticks alive (set on arrival)
    reroutes: int = 0                     # how many times this car recomputed its route

    # --- micro (cellular-automaton) motion state ---
    v: int = 0                            # speed in cells/tick
    cell: int = 0                         # cell index along the current lane
    lane: object = None                   # current lane SegId (from_node, to_node)

    @property
    def current_node(self) -> Node:
        return self.route[self.route_idx]

    @property
    def next_node(self) -> Optional[Node]:
        if self.route_idx + 1 < len(self.route):
            return self.route[self.route_idx + 1]
        return None

    def advance_index(self) -> None:
        self.route_idx += 1
