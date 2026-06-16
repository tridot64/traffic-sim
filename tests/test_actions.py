from traffic_llm.config import GridConfig, RunConfig
from traffic_llm.grid import RoadNetwork
from traffic_llm.actions import validate, tool_schemas
from traffic_llm.scenarios import get_scenario
from traffic_llm.simulation import Simulator

ALL = ("call_phase", "reroute", "close_road", "open_road", "advisory")


def _sim(rows=3, cols=3):
    return Simulator(RunConfig(grid=GridConfig(rows=rows, cols=cols),
                               scenario=get_scenario("dispatcher")))


def test_incompatible_phase_rejected():
    sim = _sim()
    acc, rej = validate(sim.net, [{"action": "call_phase", "node": "1,1", "pair": [1, 2]}],
                        ALL, sim.signals)
    assert not acc and rej[0]["reason"] == "incompatible_phase"


def test_compatible_phase_accepted():
    sim = _sim()
    acc, rej = validate(sim.net, [{"action": "call_phase", "node": "1,1", "pair": [2, 6]}],
                        ALL, sim.signals)
    assert acc and not rej
    assert acc[0]["node"] == (1, 1) and acc[0]["pair"] == (2, 6)


def test_close_that_isolates_rejected():
    net = RoadNetwork(GridConfig(rows=1, cols=2))
    acc, rej = validate(net, [{"action": "close_road", "seg": "0,0->0,1"}], ALL)
    assert not acc and rej[0]["reason"] == "isolates_node"


def test_close_with_alternative_accepted():
    net = RoadNetwork(GridConfig(rows=3, cols=3))
    acc, rej = validate(net, [{"action": "close_road", "seg": "0,0->0,1"}], ALL)
    assert acc and not rej


def test_action_not_allowed():
    sim = _sim()
    acc, rej = validate(sim.net, [{"action": "close_road", "seg": "0,0->0,1"}],
                        ("call_phase",), sim.signals)
    assert not acc and rej[0]["reason"] == "action_not_allowed"


def test_tool_schemas_filtered():
    names = {t["name"] for t in tool_schemas(("call_phase", "reroute"))}
    assert names == {"call_phase", "reroute"}
