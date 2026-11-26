import networkx as nx
import pytest
from shapely.geometry import LineString

from src import pedestrian_network as pedestrian
from src.models import Stop


ORIGIN = Stop("A", "Square", 42.70001, 23.3)
DESTINATION = Stop("B", "Park", 42.7, 23.302)
ISOLATED = Stop("C", "Island", 42.8, 23.4)
BEND = (23.3005, 42.7001)


@pytest.fixture
def graph():
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    for node, x, y in [(1, 23.3, 42.7), (2, 23.301, 42.7), (3, 23.302, 42.7), (4, 23.4, 42.8)]:
        graph.add_node(node, x=x, y=y)
    graph.add_edge(1, 3, length=300.0)
    graph.add_edge(1, 2, length=140.0)
    shape = LineString([(23.301, 42.7), BEND, (23.3, 42.7)])
    graph.add_edge(1, 2, length=100.0, geometry=shape)
    graph.add_edge(2, 3, length=80.0)
    return graph


def test_cached_graph_and_shortest_route(graph, monkeypatch, tmp_path):
    calls = []

    def download(place, *, network_type, retain_all):
        calls.append((place, network_type, retain_all))
        return graph

    monkeypatch.setattr(pedestrian.ox, "graph_from_place", download)
    pedestrian.build_pedestrian_network(cache_dir=tmp_path)
    cached = pedestrian.build_pedestrian_network(cache_dir=tmp_path)
    assert calls == [("Sofia, Bulgaria", "walk", True)]
    assert 4 in cached
    route = pedestrian.find_walking_route(cached, ORIGIN, DESTINATION, 1.5)
    assert route.node_ids == (1, 2, 3)
    assert route.geometry == ((23.3, 42.7), BEND, (23.301, 42.7), (23.302, 42.7))
    assert route.distance_meters == 180
    assert route.duration_seconds == 120


def test_unreachable_stops(graph):
    for origin, end in [(ORIGIN, ISOLATED), (DESTINATION, ORIGIN)]:
        assert pedestrian.find_walking_route(graph, origin, end, 1) is None
    assert pedestrian.find_walking_route(nx.MultiDiGraph(), ORIGIN, DESTINATION, 1) is None
    assert pedestrian.find_walking_route(graph, ORIGIN, DESTINATION, 1, max_snap_distance_m=0) is None


def test_shared_node(graph):
    route = pedestrian.find_walking_route(graph, ORIGIN, ORIGIN, 2)
    assert route.node_ids == (1,)
    assert route.geometry == ((23.3, 42.7),)
    assert route.distance_meters == route.duration_seconds == 0


@pytest.mark.parametrize("speed", [0, -1, float("nan"), float("inf")])
def test_invalid_speed(graph, speed):
    with pytest.raises(ValueError, match="walking_speed_mps"):
        pedestrian.find_walking_route(graph, ORIGIN, DESTINATION, speed)
