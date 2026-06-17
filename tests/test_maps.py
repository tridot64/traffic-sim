import json

from traffic_llm.config import GridConfig, MapConfig, RunConfig, SimConfig
from traffic_llm.grid import RoadNetwork
from traffic_llm.maps import get_map, load_map, tiered_map, TIERS, PRESETS
from traffic_llm.runner import run_single
from traffic_llm.scenarios import get_scenario
from traffic_llm.simulation import Simulator
from traffic_llm.vehicle import Car


def _quiet(scenario="signals", **grid):
    return RunConfig(grid=GridConfig(**grid),
                     sim=SimConfig(ticks=10, decision_interval=5, demand_rate=0.0),
                     scenario=get_scenario(scenario), controller="donothing", seed=0)


def test_speed_limit_override_on_grid():
    net = RoadNetwork(GridConfig(rows=3, cols=3, vmax=3,
                                 speed_limits=({"seg": "1,0->1,1", "vmax": 1, "cells": 8},)))
    assert net.segment((1, 0), (1, 1)).vmax == 1
    assert net.segment((1, 0), (1, 1)).length == 8
    assert net.segment((0, 0), (0, 1)).vmax == 3      # others unchanged


def test_slow_road_caps_car_speed():
    sim = Simulator(_quiet(rows=3, cols=3, vmax=3,
                           speed_limits=({"seg": "1,0->1,1", "vmax": 1},)))
    car = Car(id=1, origin=(1, 0), dest=(1, 2), born_tick=0, aggressiveness=1.0,
              route=[(1, 0), (1, 1), (1, 2)], route_idx=1, state="traveling",
              v=0, cell=0, lane=((1, 0), (1, 1)))
    sim.cars[car.id] = car
    sim.lanes[((1, 0), (1, 1))].place(0, car)
    for _ in range(4):
        sim.step_tick()
        if car.lane == ((1, 0), (1, 1)):
            assert car.v <= 1                          # never exceeds the 1-cell limit


def test_presets_build_and_run():
    for name in PRESETS:
        m = get_map(name)
        cfg = RunConfig(grid=GridConfig(2, 2), road_map=m,
                        sim=SimConfig(ticks=60, decision_interval=5, demand_rate=1.0),
                        scenario=get_scenario("signals"), controller="actuated", seed=0)
        sc = run_single(cfg)
        assert sc["totals"]["ticks"] == 60


def test_arterial_has_fast_middle():
    sim = Simulator(RunConfig(grid=GridConfig(5, 5), road_map=get_map("arterial"),
                              sim=SimConfig(ticks=5, decision_interval=5, demand_rate=0.0),
                              scenario=get_scenario("signals"), controller="donothing", seed=0))
    assert sim.lanes[((2, 0), (2, 1))].vmax == 6       # middle-row arterial
    assert sim.lanes[((0, 0), (0, 1))].vmax == 2       # slow street


def test_oneway_loop_is_asymmetric():
    m = get_map("oneway_loop")
    net = RoadNetwork.from_map(m)
    # clockwise perimeter present, counter-clockwise dropped
    assert ((0, 0), (0, 1)) in net.segments
    assert ((0, 1), (0, 0)) not in net.segments


def test_tiered_map_has_all_three_classes():
    net = RoadNetwork.from_map(tiered_map(6, 6, seed=0))
    vmaxes = {seg.vmax for seg in net.segments.values()}
    assert TIERS["freeway"]["vmax"] in vmaxes
    assert TIERS["expressway"]["vmax"] in vmaxes
    assert TIERS["street"]["vmax"] in vmaxes


def test_tiered_map_is_reproducible_and_runs():
    a = tiered_map(6, 6, seed=3)
    b = tiered_map(6, 6, seed=3)
    assert a.roads == b.roads                                  # seeded -> reproducible
    assert a.roads != tiered_map(6, 6, seed=4).roads
    cfg = RunConfig(grid=GridConfig(6, 6), road_map=get_map("tiered"),
                    sim=SimConfig(ticks=120, decision_interval=5, demand_rate=2.0),
                    scenario=get_scenario("dispatcher_hotspots"), controller="actuated", seed=0)
    sc = run_single(cfg)
    assert sc["competence"]["arrived"] > 0


def test_freeway_cars_outrun_street_cars():
    # a lone car reaches a higher top speed on a freeway lane than a street lane
    def top_speed(vmax):
        sim = Simulator(RunConfig(
            grid=GridConfig(2, 2, vmax=vmax, cells_per_segment=20),
            sim=SimConfig(ticks=12, decision_interval=5, demand_rate=0.0),
            scenario=get_scenario("signals"), controller="donothing", seed=0))
        car = Car(id=1, origin=(0, 0), dest=(1, 1), born_tick=0, aggressiveness=1.0,
                  route=[(0, 0), (0, 1), (1, 1)], route_idx=1, state="traveling",
                  v=0, cell=0, lane=((0, 0), (0, 1)))
        sim.cars[car.id] = car
        sim.lanes[((0, 0), (0, 1))].place(0, car)
        peak = 0
        for _ in range(8):
            sim.step_tick()
            if car.lane == ((0, 0), (0, 1)):
                peak = max(peak, car.v)
        return peak
    assert top_speed(TIERS["freeway"]["vmax"]) > top_speed(TIERS["street"]["vmax"])


def test_town_map_has_three_way_junctions_and_is_connected():
    net = RoadNetwork.from_map(get_map("town"))
    neighbors: dict = {}
    for (frm, to) in net.segments:
        neighbors.setdefault(frm, set()).add(to)
        neighbors.setdefault(to, set()).add(frm)
    three_way = {n for n, nb in neighbors.items() if len(nb) == 3}
    assert {(1, 1), (1, 2), (1, 3), (3, 2)} <= three_way    # genuine T-junctions
    # asymmetrical: not every node is degree 4 (it is NOT a full grid)
    assert any(len(nb) != 4 for nb in neighbors.values())
    # fully connected (reachable from any node)
    for n in net.nodes:
        assert net.shortest_path((1, 1), n) is not None


def test_town_map_runs_with_signals_at_t_junctions():
    sim = Simulator(RunConfig(grid=GridConfig(4, 4), road_map=get_map("town"),
                              sim=SimConfig(ticks=120, decision_interval=5, demand_rate=1.5),
                              scenario=get_scenario("signals"), controller="actuated", seed=0))
    assert (1, 1) in sim.signals and len(sim.signals[(1, 1)].valid_pairs) >= 1
    sc = run_single(RunConfig(grid=GridConfig(4, 4), road_map=get_map("town"),
                              sim=SimConfig(ticks=120, decision_interval=5, demand_rate=1.5),
                              scenario=get_scenario("signals"), controller="actuated", seed=0))
    assert sc["competence"]["arrived"] > 0


def test_load_map_json(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"roads": [{"from": "0,0", "to": "0,1", "vmax": 4},
                                       {"from": "0,1", "to": "0,0"}],
                             "default_vmax": 3, "default_cells": 10}))
    m = load_map(str(p))
    net = RoadNetwork.from_map(m)
    assert net.segment((0, 0), (0, 1)).vmax == 4
    assert net.segment((0, 1), (0, 0)).vmax == 3       # default applied
