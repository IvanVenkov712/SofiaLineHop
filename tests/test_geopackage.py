import sqlite3
from contextlib import closing
from datetime import date

import geopandas as gpd
import networkx as nx
import pytest
from shapely.geometry import LineString

from src.geopackage import StoredTransfer, read_geopackage, write_geopackage
from src.models import Stop, TransferConnection, TransferLeg, WalkingRoute
from src.pedestrian_network import find_walking_route


def test_snapshot_round_trip(tmp_path):
    path = tmp_path / "snapshot.gpkg"
    first = 2**53 + 1
    graph = nx.MultiDiGraph(crs="EPSG:32634", simplified=True)
    for i in range(3):
        graph.add_node(first + i, x=689000.0 + i, y=4730000.0, street_count=i)
    shape = LineString([(689001, 4730000), (689000.4, 4730000.3), (689000, 4730000)])
    graph.add_edge(first, first + 1, key=7, geometry=shape, length=1.6, name=["А", "Б"])
    graph.add_edge(first, first + 1, key=2, length=2.0, oneway=False)
    graph.add_edge(first + 1, first + 1, key=0, length=0.0)
    stops = [Stop("001", "Площад", 42.7, 23.3), Stop("002", "Парк", 42.71, 23.31)]
    connection = TransferConnection(TransferLeg("010", "001", None), TransferLeg("020", "002", 0))
    walk = WalkingRoute((first, first + 1), 1.6, 1.0, ((23.3, 42.7), (23.301, 42.701)))
    transfers = [StoredTransfer(connection, walk, date(2026, 11, 27), 1.6),
                 StoredTransfer(connection, WalkingRoute((first,), 0, 0, ((23.3, 42.7),))),
                 StoredTransfer(connection), StoredTransfer(connection, WalkingRoute((first,), 0, 0))]
    write_geopackage(path, stops, transfers, graph)
    stored = read_geopackage(path)
    assert stored.stops == {s.stop_id: s for s in stops}
    assert stored.transfers == transfers
    assert stored.network.graph["crs"].to_epsg() == 32634
    assert stored.network.graph["simplified"] is True
    assert isinstance(stored.network, nx.MultiDiGraph)
    assert dict(stored.network.nodes(data=True)) == dict(graph.nodes(data=True))
    assert dict(stored.network.edges) == dict(graph.edges)
    assert list(nx.isolates(stored.network)) == [first + 2]
    assert nx.shortest_path_length(stored.network, first, first + 1, weight="length") == 1.6
    with pytest.raises(nx.NetworkXNoPath):
        nx.shortest_path(stored.network, first + 1, first)

    paths = gpd.read_file(path, layer="transfer_paths")
    assert paths.crs.to_epsg() == 4326
    assert paths.geometry.iloc[1:].isna().all()
    assert tuple(paths.geometry.iloc[0].coords) == walk.geometry


def test_geopackage_registers_each_layer_and_crs(tmp_path):
    path = tmp_path / "mixed-crs.gpkg"
    graph = nx.MultiDiGraph(crs="EPSG:32634")
    graph.add_node(1, x=689000, y=4730000)
    graph.add_node(2, x=689001, y=4730000)
    graph.add_edge(1, 2, length=1)
    write_geopackage(path, [Stop("001", "Origin", 42.7, 23.3)], [], graph)

    assert path.suffix == ".gpkg"
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        assert db.execute("PRAGMA application_id").fetchone() == (0x47504B47,)
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        metadata = db.execute("""
            SELECT c.table_name, c.data_type, g.geometry_type_name, c.srs_id, g.srs_id,
                   s.organization, s.organization_coordsys_id
            FROM gpkg_contents c
            JOIN gpkg_geometry_columns g ON c.table_name = g.table_name
            JOIN gpkg_spatial_ref_sys s ON g.srs_id = s.srs_id
        """).fetchall()
    assert set(metadata) == {
        ("stops", "features", "POINT", 4326, 4326, "EPSG", 4326),
        ("transfer_paths", "features", "LINESTRING", 4326, 4326, "EPSG", 4326),
        ("pedestrian_nodes", "features", "POINT", 32634, 32634, "EPSG", 32634),
        ("pedestrian_edges", "features", "LINESTRING", 32634, 32634, "EPSG", 32634),
    }
    for layer, _, _, epsg, *_ in metadata:
        assert gpd.read_file(path, layer=layer).crs.to_epsg() == epsg

    nodes = gpd.read_file(path, layer="pedestrian_nodes").set_index("node_id")
    assert (nodes.geometry[1].x, nodes.geometry[1].y) == (689000, 4730000)


def test_restored_wgs84_graph_recalculates_the_same_walk(tmp_path):
    path = tmp_path / "walking.gpkg"
    origin = Stop("001", "Origin", 42.7, 23.300)
    destination = Stop("002", "Destination", 42.7, 23.302)
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=23.300, y=42.7)
    graph.add_node(2, x=23.301, y=42.7)
    graph.add_node(3, x=23.302, y=42.7)
    graph.add_edge(1, 2, key=4, length=125,
                   geometry=LineString([(23.301, 42.7), (23.3005, 42.7001), (23.300, 42.7)]))
    graph.add_edge(1, 2, key=8, length=175)
    graph.add_edge(2, 3, length=100)
    connection = TransferConnection(TransferLeg("010", "001", 0), TransferLeg("020", "002", 1))
    walk = find_walking_route(graph, origin, destination, 1.5, max_snap_distance_m=5)
    assert walk is not None
    assert walk.node_ids == (1, 2, 3)
    assert walk.distance_meters == 225
    assert (23.3005, 42.7001) in walk.geometry
    write_geopackage(path, [origin, destination], [StoredTransfer(connection, walk)], graph)

    restored = read_geopackage(path)
    assert nx.utils.graphs_equal(restored.network, graph)
    assert restored.transfers == [StoredTransfer(connection, walk)]
    assert find_walking_route(restored.network, restored.stops["001"], restored.stops["002"],
                              1.5, max_snap_distance_m=5) == walk


def test_empty_snapshot_and_failed_replacement(tmp_path):
    path = tmp_path / "snapshot.gpkg"
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    write_geopackage(path, [], [], graph)
    assert read_geopackage(path).network.number_of_nodes() == 0
    original = path.read_bytes()
    leg = TransferLeg("01", "absent")
    with pytest.raises(ValueError, match="absent stop"):
        write_geopackage(path, [], [StoredTransfer(TransferConnection(leg, leg))])
    assert path.read_bytes() == original
    write_geopackage(path, [], [])
    assert read_geopackage(path).network is None
    assert set(gpd.list_layers(path).name) == {"stops", "transfer_paths"}
