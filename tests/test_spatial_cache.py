import sqlite3
from contextlib import closing
from datetime import date

import networkx as nx
import pytest

from src import pedestrian_network, spatial_cache
from src.models import Route, Schedule, Stop, StopTime, Trip


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    path = tmp_path / "sofia_transport.gpkg"
    stops = {"a": Stop("a", "A", 42.7, 23.3), "b": Stop("b", "B", 42.7, 23.301)}
    trips = (Trip("in", "01", 0, (StopTime("a", 1, 0, 0),)),
             Trip("out", "02", 1, (StopTime("b", 1, 300, 300),)))
    schedule = Schedule(date(2026, 11, 27), stops, {r: Route(r, r, "") for r in ("01", "02")}, trips)
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    for i, stop in enumerate(stops.values()):
        graph.add_node(i, x=stop.longitude, y=stop.latitude)
    graph.add_edge(0, 1, length=100)
    monkeypatch.setattr(pedestrian_network, "build_pedestrian_network", lambda **kw: graph)
    return path, schedule


def test_restart_reuses_graph_search_and_walk(inputs, monkeypatch):
    path, schedule = inputs
    cache = spatial_cache.load_spatial_cache(path, schedule.stops, "release-1")
    query = (schedule, "feed-1", "01", "02", 0, 1, 500, 100)
    pair, = cache.connections(*query)
    walk = cache.walking_route(schedule, pair, 1.4, 100)
    assert cache.connections(*query[:-2], 0, 100) == []
    assert spatial_cache.cached_stops(path, None) == schedule.stops
    assert spatial_cache.cached_stops(path, "release-2") is None

    def unexpected(*args, **kwargs):
        pytest.fail("Warm spatial cache invoked acquisition or routing")

    monkeypatch.setattr(pedestrian_network, "build_pedestrian_network", unexpected)
    restored = spatial_cache.load_spatial_cache(path, schedule.stops, "release-1")
    assert restored.generation == cache.generation
    assert restored.walking_route(schedule, pair, 2.0, 100).duration_seconds == 50
    assert restored.connections(schedule, "feed-2", "01", "02", 1, 1, 500, 100) == []
    monkeypatch.setattr(spatial_cache, "find_transfers", unexpected)
    monkeypatch.setattr(pedestrian_network, "find_walking_route", unexpected)
    assert restored.connections(*query) == [pair]
    assert restored.connections(*query[:-2], 0, 100) == []
    assert restored.walking_route(schedule, pair, 1.4, 100) == walk
    updated = spatial_cache.load_spatial_cache(path, schedule.stops, "release-2")
    assert updated.generation != restored.generation
    assert not restored.is_current()


@pytest.mark.parametrize("damage", ["version", "corrupt", "missing_layer", "changed_graphml"])
def test_recovery(inputs, damage):
    path, schedule = inputs
    cached = spatial_cache.load_spatial_cache(path, schedule.stops, "release")
    if damage == "corrupt":
        path.write_bytes(b"not a database")
    elif damage == "changed_graphml":
        graphml = pedestrian_network.graphml_path(path.parent / "pedestrian")
        graphml.parent.mkdir()
        graphml.write_text("updated source")
    else:
        with closing(sqlite3.connect(path)) as db, db:
            if damage == "version":
                db.execute("UPDATE cache_info SET version=-1")
            else:
                db.execute("DROP TABLE pedestrian_nodes")
    repaired = spatial_cache.load_spatial_cache(path, schedule.stops, "release")
    assert repaired.generation != cached.generation
    assert repaired.is_current()
    assert repaired.network.edges[0, 1, 0]["length"] == 100
