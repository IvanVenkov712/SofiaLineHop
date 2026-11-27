from datetime import date

import geopandas as gpd
import networkx as nx
import pytest
from shapely.geometry import LineString

from src.geopackage import StoredTransfer, read_geopackage, write_geopackage
from src.models import Stop, TransferConnection, TransferLeg, WalkingRoute


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
    assert dict(stored.network.nodes(data=True)) == dict(graph.nodes(data=True))
    assert dict(stored.network.edges) == dict(graph.edges)
    assert nx.shortest_path_length(stored.network, first, first + 1, weight="length") == 1.6
    paths = gpd.read_file(path, layer="transfer_paths")
    assert paths.crs.to_epsg() == 4326
    assert paths.geometry.iloc[1:].isna().all()
    assert tuple(paths.geometry.iloc[0].coords) == walk.geometry


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
