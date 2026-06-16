from traffic_llm.config import GridConfig, RunConfig, SimConfig
from traffic_llm.controllers import make_controller
from traffic_llm.controllers.supervised import SupervisedActuatedController
from traffic_llm.runner import run_single
from traffic_llm.scenarios import get_scenario
from traffic_llm.simulation import Simulator


def _cfg(controller="supervised", seed=0, ticks=160, scenario="signals"):
    return RunConfig(
        grid=GridConfig(rows=4, cols=4),
        sim=SimConfig(ticks=ticks, decision_interval=5, demand_rate=1.6),
        scenario=get_scenario(scenario), controller=controller, seed=seed,
    )


class _FakeBackend:
    """Returns a fixed directive list once, then nothing."""
    name = "fake"

    def __init__(self, directives):
        self._d = directives
        self._used = False

    def decide(self, system, observation, schemas):
        if self._used:
            return [], {"backend_ms": 1.0, "failed": False, "usage": {}}
        self._used = True
        return list(self._d), {"backend_ms": 1.0, "failed": False, "usage": {}}


def test_null_supervisor_equals_actuated():
    # mock backend issues no signal directives on signals mode -> pure actuated
    sup = run_single(_cfg("supervised", seed=2))
    act = run_single(_cfg("actuated", seed=2))
    assert sup["competence"] == act["competence"]
    assert sup["safety"]["gridlock_fraction"] == act["safety"]["gridlock_fraction"]


def test_pin_overrides_algorithm():
    cfg = _cfg("supervised", scenario="dispatcher_hotspots")
    sim = Simulator(cfg)
    node = next(iter(sim.signals))
    pinned = sim.signals[node].valid_pairs[-1]   # some valid, possibly non-default pair
    ctrl = SupervisedActuatedController(
        _FakeBackend([{"action": "pin_phase", "node": f"{node[0]},{node[1]}",
                       "pair": list(pinned), "ticks": 30}]), llm_interval=1)
    raw, _ = ctrl.decide(sim)
    call = next(a for a in raw if a["action"] == "call_phase"
                and a["node"] == f"{node[0]},{node[1]}")
    assert tuple(call["pair"]) == pinned          # strongarm honored


def test_bias_shifts_choice_and_bad_target_rejected():
    cfg = _cfg("supervised", scenario="dispatcher_hotspots")
    sim = Simulator(cfg)
    node = next(iter(sim.signals))
    fav = sim.signals[node].valid_pairs[-1]
    ctrl = SupervisedActuatedController(
        _FakeBackend([
            {"action": "bias_phase", "node": f"{node[0]},{node[1]}", "pair": list(fav), "weight": 50},
            {"action": "bias_phase", "node": "9,9", "pair": list(fav), "weight": 5},  # bad node
        ]), llm_interval=1)
    raw, meta = ctrl.decide(sim)
    call = next(a for a in raw if a["action"] == "call_phase"
                and a["node"] == f"{node[0]},{node[1]}")
    assert tuple(call["pair"]) == fav             # heavy bias wins the choice
    assert any(r["reason"] == "bad_bias_target" for r in meta["controller_rejected"])


def test_make_controller_supervised():
    c = make_controller("supervised", backend="mock")
    assert isinstance(c, SupervisedActuatedController)
