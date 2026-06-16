from traffic_llm.config import GridConfig
from traffic_llm.grid import RoadNetwork, seg_key, parse_seg_key


def test_grid_shape_and_segments():
    net = RoadNetwork(GridConfig(rows=3, cols=3))
    assert len(net.nodes) == 9
    # interior node (1,1) has 4 outgoing; corner (0,0) has 2
    assert len(net.outgoing((1, 1))) == 4
    assert len(net.outgoing((0, 0))) == 2


def test_direction_into():
    net = RoadNetwork(GridConfig(rows=3, cols=3))
    node = (1, 1)
    assert net.direction_into(node, (0, 1)) == "N"
    assert net.direction_into(node, (2, 1)) == "S"
    assert net.direction_into(node, (1, 0)) == "W"
    assert net.direction_into(node, (1, 2)) == "E"


def test_shortest_path_and_avoid():
    net = RoadNetwork(GridConfig(rows=3, cols=3))
    path = net.shortest_path((0, 0), (2, 2))
    assert path[0] == (0, 0) and path[-1] == (2, 2)
    assert len(path) == 5  # manhattan distance 4 + 1 nodes

    # closing the only outward segments from origin makes dest unreachable
    net.segment((0, 0), (0, 1)).closed_operator = True
    net.segment((0, 0), (1, 0)).closed_operator = True
    assert net.shortest_path((0, 0), (2, 2)) is None


def test_seg_key_roundtrip():
    assert parse_seg_key(seg_key((1, 2), (1, 3))) == ((1, 2), (1, 3))
