from traffic_llm.config import GridConfig, RunConfig, SimConfig
from traffic_llm.controllers import make_controller
from traffic_llm.runner import run_single
from traffic_llm.scenarios import get_scenario
from traffic_llm.simulation import Simulator


def _cfg(controller="actuated", seed=0, ticks=160, scenario="signals"):
    return RunConfig(
        grid=GridConfig(rows=4, cols=4),
        sim=SimConfig(ticks=ticks, decision_interval=5, demand_rate=1.6),
        scenario=get_scenario(scenario), controller=controller, seed=seed,
    )


def test_engine_conserves_cars_and_is_collision_free():
    cfg = _cfg()
    sim = Simulator(cfg)
    controller = make_controller("actuated")
    states_seen = set()
    for t in range(cfg.sim.ticks):
        if t % cfg.sim.decision_interval == 0:
            raw, _ = controller.decide(sim)
            sim.apply_actions(raw)
        sim.step_tick()
        # collect every active car id and its (lane, cell)
        ids = []
        for seg, lane in sim.lanes.items():
            for i, car in enumerate(lane.cells):
                if car is not None:
                    assert 0 <= i < lane.length
                    ids.append(car.id)
        ids += [c.id for c in sim.pending]
        assert len(ids) == len(set(ids))          # no car duplicated / teleported
        assert set(ids) == set(sim.cars)          # conservation
        for sig in sim.signals.values():
            states_seen.add(sig.state)
    assert sim.arrived_total > 0
    # NEMA clearance must actually occur as the actuated controller switches
    assert "yellow" in states_seen and "allred" in states_seen


def test_determinism():
    assert run_single(_cfg(seed=3)) == run_single(_cfg(seed=3))


def test_actuated_beats_donothing():
    a = run_single(_cfg("actuated", seed=1))
    d = run_single(_cfg("donothing", seed=1))
    assert a["competence"]["throughput_per_tick"] > d["competence"]["throughput_per_tick"]


def test_advisory_decays():
    from traffic_llm.micro.engine import ADVISORY_TTL
    sim = Simulator(RunConfig(grid=GridConfig(4, 4),
        sim=SimConfig(ticks=100, decision_interval=5, demand_rate=0.0),
        scenario=get_scenario("dispatcher"), controller="donothing", seed=0))
    seg = ((1, 1), (1, 2))
    sim.apply_actions([{"action": "advisory", "text": "x", "avoid": ["1,1->1,2"]}])
    assert seg in sim.global_avoid                  # active now
    for _ in range(ADVISORY_TTL + 1):
        sim.step_tick()
    assert seg not in sim.global_avoid              # decayed, did not accumulate


def test_proactive_reroute_diverts_early():
    from traffic_llm.vehicle import Car
    sim = Simulator(RunConfig(grid=GridConfig(3, 3),
        sim=SimConfig(ticks=10, decision_interval=5, demand_rate=0.0),
        scenario=get_scenario("dispatcher"), controller="donothing", seed=0))
    # car en route (0,0)->(0,1)->(0,2)->(1,2), approaching (0,1); close a link 2 hops ahead
    car = Car(id=999, origin=(0, 0), dest=(1, 2), born_tick=0, aggressiveness=0.5,
              route=[(0, 0), (0, 1), (0, 2), (1, 2)], route_idx=1, state="traveling",
              v=1, cell=4, lane=((0, 0), (0, 1)))
    sim.cars[car.id] = car
    sim.net.segment((0, 2), (1, 2)).closed_operator = True
    sim._proactive_reroute()
    assert car.reroutes > 0                                   # diverted early
    seg_pairs = list(zip(car.route, car.route[1:]))
    assert ((0, 2), (1, 2)) not in seg_pairs                  # avoids the closure
    assert car.route[-1] == (1, 2)                            # still reaches dest


def test_hotspots_skew_destinations():
    cfg = RunConfig(
        grid=GridConfig(rows=4, cols=4),
        sim=SimConfig(ticks=80, decision_interval=5, demand_rate=2.0),
        scenario=get_scenario("both_hotspots"), controller="actuated", seed=0,
    )
    sim = Simulator(cfg)
    for _ in range(60):                 # within the 0,3 hotspot window (start 0, end 120)
        sim.step_tick()
    dests = [c.dest for c in sim.cars.values()]
    frac_hot = sum(1 for d in dests if d == (0, 3)) / max(1, len(dests))
    assert frac_hot > 0.15              # vs ~1/16 = 0.06 uniform
    obs = sim.observation()
    assert any(h["node"] == "0,3" for h in obs["hotspots"])
