"""Road network topology: an ``rows x cols`` grid of intersections joined by
bidirectional, single-direction-per-segment road links.

This module is pure topology + routing. All time-varying dynamics (queues,
cars in motion, signal phases) live in ``simulation.py``.
"""

from __future__ import annotations

from collections import deque
from typing import Iterable, Optional

from .config import GridConfig

Node = tuple[int, int]
SegId = tuple[Node, Node]  # (from_node, to_node)

# Approach letters as seen *at the downstream node*. 'N' means the segment
# arrives from the node to the north. N/S share the vertical axis; E/W the
# horizontal axis. Two greens conflict iff they are on different axes.
AXIS = {"N": "V", "S": "V", "E": "H", "W": "H"}


def seg_key(frm: Node, to: Node) -> str:
    """Stable string id for logs/JSON, e.g. ``'0,1->0,2'``."""
    return f"{frm[0]},{frm[1]}->{to[0]},{to[1]}"


def parse_seg_key(s: str) -> SegId:
    a, b = s.split("->")
    fr = tuple(int(x) for x in a.split(","))
    to = tuple(int(x) for x in b.split(","))
    return (fr, to)  # type: ignore[return-value]


class Segment:
    """A one-way road link from ``frm`` to ``to``.

    ``closed_event`` and ``closed_operator`` are tracked separately so the
    simulator can distinguish a shock-induced closure from an operator
    (LLM/dispatcher) closure. A segment is impassable if either is set. Physical
    capacity lives in the micro engine's cellular lanes, not here.
    """

    __slots__ = ("frm", "to", "closed_event", "closed_operator")

    def __init__(self, frm: Node, to: Node):
        self.frm = frm
        self.to = to
        self.closed_event = False
        self.closed_operator = False

    @property
    def closed(self) -> bool:
        return self.closed_event or self.closed_operator

    @property
    def key(self) -> str:
        return seg_key(self.frm, self.to)


class RoadNetwork:
    def __init__(self, cfg: GridConfig):
        self.cfg = cfg
        self.rows = cfg.rows
        self.cols = cfg.cols
        self.nodes: list[Node] = [(r, c) for r in range(cfg.rows) for c in range(cfg.cols)]
        self.segments: dict[SegId, Segment] = {}
        self._adj: dict[Node, list[SegId]] = {n: [] for n in self.nodes}

        for (r, c) in self.nodes:
            for (nr, nc) in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                if 0 <= nr < cfg.rows and 0 <= nc < cfg.cols:
                    frm, to = (r, c), (nr, nc)
                    self.segments[(frm, to)] = Segment(frm, to)
                    self._adj[frm].append((frm, to))

    # ---- lookups -------------------------------------------------------
    def segment(self, frm: Node, to: Node) -> Segment:
        return self.segments[(frm, to)]

    def outgoing(self, node: Node) -> list[SegId]:
        return self._adj[node]

    def direction_into(self, node: Node, frm: Node) -> str:
        """Approach letter at ``node`` for a segment arriving from ``frm``."""
        dr, dc = node[0] - frm[0], node[1] - frm[1]
        if dr == 1:
            return "N"
        if dr == -1:
            return "S"
        if dc == 1:
            return "W"
        if dc == -1:
            return "E"
        raise ValueError(f"{frm} is not adjacent to {node}")

    # ---- routing -------------------------------------------------------
    def shortest_path(
        self,
        src: Node,
        dst: Node,
        avoid: Optional[Iterable[SegId]] = None,
        respect_closed: bool = True,
    ) -> Optional[list[Node]]:
        """BFS shortest path (unit edge weights) from ``src`` to ``dst``.

        Segments in ``avoid`` and (if ``respect_closed``) closed segments are
        treated as missing edges. Returns the node list, or ``None`` if no path
        exists — which is itself meaningful (a closure that isolates a
        destination is a safety problem).
        """
        if src == dst:
            return [src]
        avoid_set = set(avoid) if avoid else set()
        prev: dict[Node, Node] = {src: src}
        q: deque[Node] = deque([src])
        while q:
            cur = q.popleft()
            for (frm, to) in self._adj[cur]:
                if to in prev:
                    continue
                if (frm, to) in avoid_set:
                    continue
                if respect_closed and self.segments[(frm, to)].closed:
                    continue
                prev[to] = cur
                if to == dst:
                    return self._reconstruct(prev, src, dst)
                q.append(to)
        return None

    @staticmethod
    def _reconstruct(prev: dict[Node, Node], src: Node, dst: Node) -> list[Node]:
        path = [dst]
        while path[-1] != src:
            path.append(prev[path[-1]])
        path.reverse()
        return path
