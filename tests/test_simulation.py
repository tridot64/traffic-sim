from traffic_llm.config import GridConfig, RunConfig, SimConfig
from traffic_llm.runner import run_single
from traffic_llm.scenarios import get_scenario
from traffic_llm.simulation import Simulator


def _cfg(controller="maxpressure", seed=0, ticks=120, scenario="both"):
    return RunConfig(
        grid=GridConfig(rows=4, cols=4),
        sim=SimConfig(ticks=ticks, decision_interval=10, demand_rate=3.0),
        scenario=get_scenario(scenario),
        controller=controller, backend="mock", seed=seed,
    )


def test_cars_arrive():
    sc = run_single(_cfg("donothing", scenario="both_calm"))
    assert sc["competence"]["arrived"] > 0
    assert sc["totals"]["spawned"] >= sc["competence"]["arrived"]


def test_determinism_same_seed():
    a = run_single(_cfg(seed=1))
    b = run_single(_cfg(seed=1))
    assert a == b  # exact reproducibility


def test_different_seeds_differ():
    a = run_single(_cfg(seed=1))
    b = run_single(_cfg(seed=2))
    assert a != b


def test_scorecard_keys():
    sc = run_single(_cfg("llm", scenario="dispatcher"))
    assert set(sc) == {"competence", "safety", "robustness", "decisions", "totals"}
    assert "gridlock_fraction" in sc["safety"]
    assert "mean_recovery_ticks" in sc["robustness"]


def test_disallowed_closure_rejected():
    cfg = _cfg("donothing", scenario="both_calm", ticks=5)
    sim = Simulator(cfg)
    seg = ((0, 0), (0, 1))
    accepted, rejected = sim.apply_actions([{"action": "close_road", "seg": "0,0->0,1"}])
    # 'both' control mode doesn't allow close_road -> rejected, not applied
    assert not accepted and rejected[0]["reason"] == "action_not_allowed"
    assert sim.net.segments[seg].closed_operator is False


def test_dispatcher_closure_applied():
    cfg = _cfg("donothing", scenario="dispatcher", ticks=5)
    sim = Simulator(cfg)
    seg = ((0, 0), (0, 1))
    accepted, rejected = sim.apply_actions([{"action": "close_road", "seg": "0,0->0,1"}])
    assert accepted and not rejected
    assert sim.net.segments[seg].closed_operator is True
