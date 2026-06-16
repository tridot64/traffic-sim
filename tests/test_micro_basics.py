import random

from traffic_llm.micro.movements import (
    heading_of, turn_type, COMPATIBLE_PAIRS, pair_movements, discharge_kind,
    is_compatible_pair,
)
from traffic_llm.micro.cells import Lane, ns_new_speed, p_slow_for


# ---- NEMA movement geometry ----
def test_heading_of():
    assert heading_of((0, 0), (1, 0)) == "S"
    assert heading_of((1, 0), (0, 0)) == "N"
    assert heading_of((0, 0), (0, 1)) == "E"
    assert heading_of((0, 1), (0, 0)) == "W"


def test_turn_type():
    assert turn_type("N", "N") == "T"
    assert turn_type("N", "W") == "L"   # heading north, exit west = left
    assert turn_type("N", "E") == "R"
    assert turn_type("E", "N") == "L"


def test_compatible_pairs_are_conflict_free():
    # every compatible pair's protected greens must not contain two opposing
    # *through* movements crossing each other; cross-street throughs never co-occur
    for pair in COMPATIBLE_PAIRS:
        assert is_compatible_pair(pair)
        mv = pair_movements(pair)
        throughs = {h for (h, t) in mv if t == "T"}
        # a pair only ever serves one street, so throughs share an axis
        axes = {("V" if h in ("N", "S") else "H") for h in throughs}
        assert len(axes) <= 1


def test_discharge_kinds():
    green = pair_movements((2, 6))  # WBT + EBT (both E-W throughs)
    assert discharge_kind(("W", "T"), green) == "protected"
    assert discharge_kind(("E", "L"), green) == "permissive"   # left vs opposing WBT
    assert discharge_kind(("N", "R"), green) == "rtor"
    assert discharge_kind(("N", "T"), green) == "blocked"


# ---- CA physics ----
def test_p_slow_aggressiveness():
    assert p_slow_for(1.0, 0.3) == 0.0     # fully aggressive: never dawdles
    assert p_slow_for(0.0, 0.3) == 0.3     # timid: full base rate


def test_ns_speed_brakes_to_gap():
    rng = random.Random(0)
    assert ns_new_speed(v=3, gap=1, vmax=3, p_slow=0.0, rng=rng) == 1
    assert ns_new_speed(v=0, gap=5, vmax=3, p_slow=0.0, rng=rng) == 1  # accel by 1


def _single_lane_step(lane: Lane, vmap: dict, vmax: int, rng):
    """Synchronous NS update on one closed lane (stop line is a wall)."""
    idxs = lane.occupied_indices_desc()
    new = {}
    for i in idxs:
        car = lane.at(i)
        gap = lane.gap_ahead(i)
        new[i] = ns_new_speed(vmap[car], gap, vmax, 0.0, rng)
    # move (front-to-back so we never write an occupied cell)
    for i in idxs:
        car = lane.at(i)
        v = new[i]
        if v:
            lane.remove(i)
            lane.place(i + v, car)
        vmap[car] = v


def test_single_lane_collision_free_and_progress():
    rng = random.Random(0)
    lane = Lane(length=12)
    cars = ["a", "b", "c"]
    for k, c in enumerate(cars):
        lane.place(k, c)
    vmap = {c: 0 for c in cars}
    for _ in range(30):
        _single_lane_step(lane, vmap, vmax=3, rng=rng)
        occ = [i for i in range(lane.length) if lane.at(i) is not None]
        assert len(occ) == len(set(occ)) == 3   # never lose or overlap a car
    # all cars have advanced toward the stop line
    assert lane.at(11) is not None
