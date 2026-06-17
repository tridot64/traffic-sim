"""Microscopic traffic engine.

Each tick:
  1. advance the seeded event stream (closures / surges),
  2. step every intersection's NEMA signal clearance machine,
  3. move cars — first the lead cars crossing intersections (subject to
     protected/permissive/RTOR rules + gap acceptance + downstream space),
     then Nagel-Schreckenberg car-following within each lane,
  4. inject new demand at origins.

All randomness comes from one seeded RNG, so runs are exactly reproducible.
Route index convention: while a car is on lane (A,B), ``route_idx`` indexes B
in its route — i.e. ``current_node`` is the intersection it is approaching.
"""

from __future__ import annotations

import math
import random
from typing import Any, Optional

from ..config import RunConfig
from ..events import EventScheduler
from ..grid import Node, RoadNetwork, SegId, seg_key
from ..vehicle import Car
from .cells import Lane, ns_new_speed, p_slow_for
from .movements import (
    discharge_kind, heading_of, turn_type, COMPATIBLE_PAIRS, pair_movements,
)
from .signal import IntersectionSignal

MAX_ACTIVE_CARS = 8000
ADVISORY_TTL = 40       # ticks an LLM routing advisory stays in effect before decaying


class MicroSimulator:
    def __init__(self, cfg: RunConfig):
        self.cfg = cfg
        self.net = (RoadNetwork.from_map(cfg.road_map) if cfg.road_map
                    else RoadNetwork(cfg.grid))
        self.rng = random.Random(cfg.seed)
        self.events = EventScheduler(self.net, cfg.scenario, self.rng)

        # one CA lane per road, sized + speed-limited per segment
        self.lanes: dict[SegId, Lane] = {
            s: Lane(seg.length, seg.vmax) for s, seg in self.net.segments.items()}

        self.existing_moves: dict[Node, set[tuple[str, str]]] = {}
        self.signals: dict[Node, IntersectionSignal] = {}
        for node in self.net.nodes:
            mv = self._movements_at(node)
            self.existing_moves[node] = mv
            if mv:
                self.signals[node] = IntersectionSignal(node, mv, cfg.signal)

        self.cars: dict[int, Car] = {}
        self.pending: list[Car] = []
        self._next_id = 0

        self.node_avoid: dict[Node, set[SegId]] = {}
        self.global_avoid: set[SegId] = set()
        self._advisory_expiry: dict[SegId, int] = {}   # advisories decay, don't accumulate
        self.last_advisory = ""

        # destination hotspots: (node, weight, start_tick, end_tick)
        self._node_index = {n: i for i, n in enumerate(self.net.nodes)}
        self.hotspots: list[tuple[Node, float, int, int]] = []
        for h in cfg.scenario.hotspots:
            r, c = (int(x) for x in h["node"].split(","))
            if (r, c) in self._node_index:   # ignore hotspots outside this grid
                self.hotspots.append((
                    (r, c), float(h.get("weight", 3.0)),
                    int(h.get("start", 0)), int(h.get("end", 10 ** 9)),
                ))

        self.tick = 0
        self.arrived_total = 0
        self.spawned_total = 0
        self.sum_travel = self.sum_wait = 0
        self.travel_times: list[int] = []
        self.wait_times: list[int] = []
        self._crossed = 0
        self._stopped = 0
        self._arrived_tick = 0

    # ------------------------------------------------------------------
    def _movements_at(self, node: Node) -> set[tuple[str, str]]:
        incoming = [(frm, node) for (frm, to) in self.net.segments if to == node]
        outgoing = [(node, nxt) for (n, nxt) in self.net.segments if n == node]
        moves: set[tuple[str, str]] = set()
        for (frm, _) in incoming:
            h_in = heading_of(frm, node)
            for (_, nxt) in outgoing:
                t = turn_type(h_in, heading_of(node, nxt))
                if t != "U":
                    moves.add((h_in, t))
        return moves

    def _avoid(self, node: Node) -> set[SegId]:
        return self.global_avoid | self.node_avoid.get(node, set())

    # ------------------------------------------------------------------
    def step_tick(self) -> list[dict[str, Any]]:
        self._crossed = 0
        self._arrived_tick = 0
        self._expire_advisories()
        fired = self.events.step(self.tick)
        for sig in self.signals.values():
            sig.step()
        self._proactive_reroute()
        self._movement_phase()
        self._inject_demand()
        self.tick += 1
        return fired

    def _expire_advisories(self) -> None:
        for seg, exp in list(self._advisory_expiry.items()):
            if exp <= self.tick:
                del self._advisory_expiry[seg]
                self.global_avoid.discard(seg)

    def _proactive_reroute(self) -> None:
        """Cars divert as soon as ANY segment on their remaining route is closed
        or advised-against — not only when they reach the intersection before it.
        Skipped entirely when nothing is closed/advised (the common case)."""
        blocked_set = self.global_avoid | {
            s for s, seg in self.net.segments.items() if seg.closed}
        if not blocked_set:
            return
        for car in self.cars.values():
            if car.state != "traveling":
                continue
            r, i = car.route, car.route_idx
            if any((r[j], r[j + 1]) in blocked_set for j in range(i, len(r) - 1)):
                self._reroute(car, self.global_avoid)   # re-plan from current node

    # ------------------------------------------------------------------
    def _movement_phase(self) -> None:
        just_crossed: set[int] = set()

        # PHASE 1 — lead cars crossing intersections
        for seg in sorted(self.lanes, key=lambda s: seg_key(*s)):
            lane = self.lanes[seg]
            idxs = lane.occupied_indices_desc()
            if not idxs:
                continue
            lead_i = idxs[0]
            car = lane.at(lead_i)
            if lead_i + min(car.v + 1, lane.vmax) < lane.length - 1:
                continue  # cannot reach the stop line this tick (own road's limit)
            node = seg[1]
            if node == car.dest:                       # arrival
                lane.remove(lead_i)
                self._arrive(car)
                self._crossed += 1
                continue
            target = self._next_lane(car, node)
            if target is None:
                continue                               # blocked / no route — waits
            heading = heading_of(seg[0], node)
            turn = turn_type(heading, heading_of(node, target[1]))
            sig = self.signals[node]
            kind = discharge_kind((heading, turn), sig.protected_movements())
            if kind == "blocked":
                continue
            if kind in ("permissive", "rtor"):
                if not sig.is_green() or self.rng.random() >= car.aggressiveness:
                    continue                           # yield / gap not accepted
            tlane = self.lanes[target]
            if not tlane.free(0):
                continue                               # no room downstream
            lane.remove(lead_i)
            car.advance_index()
            car.lane = target
            car.cell = 0
            car.v = min(max(car.v, 1), tlane.vmax)   # obey the new road's limit
            tlane.place(0, car)
            just_crossed.add(car.id)
            self._crossed += 1

        # PHASE 2 — Nagel-Schreckenberg car-following within each lane
        stopped = 0
        for seg in sorted(self.lanes, key=lambda s: seg_key(*s)):
            lane = self.lanes[seg]
            idxs = lane.occupied_indices_desc()
            plan = []
            for i in idxs:
                car = lane.at(i)
                if car.id in just_crossed:
                    continue
                gap = lane.gap_ahead(i)
                ps = p_slow_for(car.aggressiveness, self.cfg.sim.p_slow)
                plan.append((i, car, ns_new_speed(car.v, gap, lane.vmax, ps, self.rng)))
            for i, car, nv in plan:
                car.v = nv
                if nv > 0:
                    lane.remove(i)
                    lane.place(i + nv, car)
                    car.cell = i + nv
                else:
                    car.wait_ticks += 1
                    stopped += 1
        self._stopped = stopped + len(self.pending)

    def _next_lane(self, car: Car, node: Node) -> Optional[SegId]:
        """The lane the car wants next, rerouting around closed/avoided links."""
        nxt = car.next_node
        avoid = self._avoid(node)
        target = (node, nxt) if nxt is not None else None
        if target is None or self.net.segments.get(target) is None \
                or self.net.segments[target].closed or target in avoid:
            if not self._reroute(car, avoid):
                return None
            nxt = car.next_node
            target = (node, nxt)
            if nxt is None or self.net.segments[target].closed:
                return None
        return target

    def _reroute(self, car: Car, avoid: set[SegId]) -> bool:
        path = self.net.shortest_path(car.current_node, car.dest, avoid=avoid)
        if path is None or len(path) < 2:
            return False
        car.route = path
        car.route_idx = 0
        car.reroutes += 1
        return True

    def _arrive(self, car: Car) -> None:
        car.state = "arrived"
        car.travel_ticks = self.tick - car.born_tick
        self.arrived_total += 1
        self.sum_travel += car.travel_ticks
        self.sum_wait += car.wait_ticks
        self.travel_times.append(car.travel_ticks)
        self.wait_times.append(car.wait_ticks)
        self._arrived_tick += 1
        self.cars.pop(car.id, None)

    # ------------------------------------------------------------------
    def _inject_demand(self) -> None:
        if len(self.cars) < MAX_ACTIVE_CARS:
            lam = self.cfg.sim.demand_rate * self.events.demand_multiplier
            for _ in range(_poisson(self.rng, lam)):
                self._spawn()
        still: list[Car] = []
        for car in self.pending:
            first = (car.route[0], car.route[1])
            lane = self.lanes[first]
            if not self.net.segments[first].closed and lane.free(0):
                lane.place(0, car)
                car.lane = first
                car.cell = 0
                car.v = 0
                car.state = "traveling"
            else:
                car.wait_ticks += 1
                still.append(car)
        self.pending = still

    def _active_hotspots(self) -> list[tuple[Node, float]]:
        return [(n, w) for (n, w, s, e) in self.hotspots if s <= self.tick < e]

    def _spawn(self) -> None:
        nodes = self.net.nodes
        origin = self.rng.choice(nodes)
        active = self._active_hotspots()
        if active:
            weights = [1.0] * len(nodes)
            for (hn, w) in active:
                weights[self._node_index[hn]] += w
            dest = self.rng.choices(nodes, weights=weights, k=1)[0]
        else:
            dest = self.rng.choice(nodes)
        if dest == origin:
            return
        path = self.net.shortest_path(origin, dest, avoid=self.global_avoid)
        if path is None or len(path) < 2:
            return
        aggr = min(1.0, max(0.0, self.rng.gauss(
            self.cfg.sim.aggressiveness_mean, self.cfg.sim.aggressiveness_std)))
        car = Car(id=self._next_id, origin=origin, dest=dest, born_tick=self.tick,
                  aggressiveness=aggr, route=path, route_idx=1, state="queued")
        self._next_id += 1
        self.spawned_total += 1
        self.cars[car.id] = car
        self.pending.append(car)

    # ------------------------------------------------------------------
    # demand introspection used by white-box baselines
    # ------------------------------------------------------------------
    def movement_waiting(self, node: Node) -> dict[tuple[str, str], int]:
        """Count of stopped cars on each incoming approach wanting each movement
        (the 'pressure plate' reading)."""
        out: dict[tuple[str, str], int] = {}
        for (frm, to) in self.net.segments:
            if to != node:
                continue
            lane = self.lanes[(frm, to)]
            h_in = heading_of(frm, node)
            for i in lane.occupied_indices_desc():
                car = lane.at(i)
                if car.v != 0:
                    continue
                nxt = car.next_node
                if nxt is None:
                    continue
                t = turn_type(h_in, heading_of(node, nxt))
                if t == "U":
                    continue
                out[(h_in, t)] = out.get((h_in, t), 0) + 1
        return out

    def pair_pressure(self, node: Node) -> dict[tuple[int, int], int]:
        demand = self.movement_waiting(node)
        sig = self.signals[node]
        return {p: sum(demand.get(m, 0) for m in pair_movements(p) & sig.existing)
                for p in sig.valid_pairs}

    # ------------------------------------------------------------------
    def apply_actions(self, raw_actions: list[dict[str, Any]]):
        from ..actions import validate  # local import avoids cycle
        accepted, rejected = validate(self.net, raw_actions,
                                      self.cfg.scenario.allowed_actions, self.signals)
        for a in accepted:
            kind = a["action"]
            if kind == "call_phase":
                self.signals[a["node"]].request_pair(a["pair"])
            elif kind == "reroute":
                self.node_avoid[a["node"]] = set(a["avoid"])
            elif kind == "advisory":
                for seg in a["avoid"]:                  # decays after ADVISORY_TTL
                    self._advisory_expiry[seg] = self.tick + ADVISORY_TTL
                    self.global_avoid.add(seg)
                self.last_advisory = a.get("text", "")
            elif kind == "close_road":
                self.net.segments[a["seg"]].closed_operator = True
            elif kind == "open_road":
                self.net.segments[a["seg"]].closed_operator = False
        return accepted, rejected

    # ------------------------------------------------------------------
    @property
    def total_queue(self) -> int:
        return self._stopped

    def _mean_wait(self) -> float:
        return round(self.sum_wait / self.arrived_total, 2) if self.arrived_total else 0.0

    def _mean_travel(self) -> float:
        return round(self.sum_travel / self.arrived_total, 2) if self.arrived_total else 0.0

    # ------------------------------------------------------------------
    def observation(self) -> dict[str, Any]:
        """Rich situation report (A: real topology + per-movement demand,
        C: closures/surge horizon). Memory (B) is added controller-side."""
        nodes: dict[str, Any] = {}
        for node, sig in self.signals.items():
            demand = self.movement_waiting(node)
            nodes[f"{node[0]},{node[1]}"] = {
                "active_pair": list(sig.active_pair),
                "state": sig.state,
                "time_in_pair": sig.time_in_pair,
                "valid_pairs": [list(p) for p in sig.valid_pairs],
                "waiting_by_movement": {f"{h}{t}": c for (h, t), c in sorted(demand.items())},
                "waiting_total": sum(demand.values()),
            }
        lanes: dict[str, Any] = {}
        for seg, lane in self.lanes.items():
            occ = sum(1 for c in lane.cells if c is not None)
            lanes[seg_key(*seg)] = {"occ": occ, "len": lane.length,
                                    "closed": self.net.segments[seg].closed}
        closed = [seg_key(*s) for s, sg in self.net.segments.items() if sg.closed]
        return {
            "tick": self.tick,
            "control_mode": self.cfg.scenario.control_mode,
            "allowed_actions": list(self.cfg.scenario.allowed_actions),
            "active_cars": len(self.cars),
            "arrived_total": self.arrived_total,
            "total_queue": self.total_queue,
            "demand_multiplier": self.events.demand_multiplier,
            "closed_segments": closed,
            "hotspots": self._hotspot_report(),
            "nodes": nodes,
            "lanes": lanes,
            "mean_wait": self._mean_wait(),
        }

    def _hotspot_report(self) -> list[dict[str, Any]]:
        """Active destination hotspots with their current inflow (cars en route)."""
        out = []
        for (n, w) in self._active_hotspots():
            inflow = sum(1 for c in self.cars.values() if c.dest == n)
            out.append({"node": f"{n[0]},{n[1]}", "weight": w, "inflow": inflow})
        return out

    def snapshot(self, fired: list[dict[str, Any]]) -> dict[str, Any]:
        gridlocked = self._stopped > 0 and self._crossed == 0
        return {
            "tick": self.tick - 1,
            "active_cars": len(self.cars),
            "arrived_total": self.arrived_total,
            "arrived": self._arrived_tick,
            "discharged": self._crossed,
            "total_queue": self.total_queue,
            "mean_wait": self._mean_wait(),
            "mean_travel": self._mean_travel(),
            "closed_count": sum(1 for s in self.net.segments.values() if s.closed),
            "demand_multiplier": self.events.demand_multiplier,
            "gridlocked": gridlocked,
            "events": fired,
            "hotspots": self._hotspot_report(),
            "lanes": {
                seg_key(*s): {
                    "cars": [i for i, c in enumerate(lane.cells) if c is not None],
                    "len": lane.length,
                    "vmax": lane.vmax,
                    "closed": self.net.segments[s].closed,
                }
                for s, lane in self.lanes.items()
            },
            "signals": {
                f"{n[0]},{n[1]}": {
                    "pair": list(sig.active_pair),
                    "state": sig.state,
                    "greens": [f"{h}{t}" for (h, t) in sorted(sig.protected_movements())],
                }
                for n, sig in self.signals.items()
            },
        }


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    L = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1
