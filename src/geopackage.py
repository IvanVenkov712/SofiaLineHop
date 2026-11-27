"""Read and write SofiaLineHop spatial snapshots as OGC GeoPackages."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from operator import index
from pathlib import Path
from tempfile import TemporaryDirectory

import geopandas as gpd
import networkx as nx
import pandas as pd
from pyogrio import read_info
from shapely.geometry import LineString, Point

from .models import Stop, TransferConnection, TransferLeg, WalkingRoute

WGS84 = "EPSG:4326"


@dataclass(frozen=True)
class StoredTransfer:
    connection: TransferConnection
    walk: WalkingRoute | None = None
    service_date: date | None = None
    walking_speed_mps: float | None = None


@dataclass
class SpatialSnapshot:
    stops: dict[str, Stop]
    transfers: list[StoredTransfer]
    network: nx.MultiDiGraph | None


def _write_layer(path, name, rows, fields, crs, geometry_type, **options):
    # Explicit dtypes also give empty and entirely null layers their intended schema.
    table = pd.DataFrame.from_records(rows, columns=[*fields, "geometry"]).astype(fields)
    frame = gpd.GeoDataFrame(table, geometry="geometry", crs=crs)
    frame.to_file(path, layer=name, driver="GPKG", engine="pyogrio", index=False,
                  geometry_type=geometry_type, **options)


def _attributes(data, omit):
    attrs = {key: value for key, value in data.items() if key not in omit}
    encoded = json.dumps(attrs, ensure_ascii=False, allow_nan=False)
    if json.loads(encoded) != attrs:
        raise ValueError("Graph attributes must round-trip as JSON values with string keys")
    return encoded


def _write_network(path, graph):
    if not isinstance(graph, nx.MultiDiGraph):
        raise TypeError("Expected a directed pedestrian MultiDiGraph")
    crs = graph.graph["crs"]
    if crs is None:
        raise ValueError("Pedestrian network requires a CRS")

    nodes = ((index(node), _attributes(data, {"x", "y"}), Point(data["x"], data["y"]))
             for node, data in graph.nodes(data=True))
    _write_layer(path, "pedestrian_nodes", nodes, {"node_id": "int64", "attrs": "string"},
                 crs, "Point", layer_metadata={"graph_attrs": _attributes(graph.graph, {"crs"})})

    def edges():
        for u, v, key, data in graph.edges(keys=True, data=True):
            shape = data.get("geometry")
            if shape is None:
                shape = LineString([(graph.nodes[n]["x"], graph.nodes[n]["y"]) for n in (u, v)])
            explicit = data.get("geometry") is not None
            omit = {"length", "geometry"} if explicit else {"length"}
            yield u, v, index(key), data["length"], explicit, _attributes(data, omit), shape

    _write_layer(path, "pedestrian_edges", edges(),
                 {"u": "int64", "v": "int64", "edge_key": "int64", "length_m": "float64",
                  "has_shape": "bool", "attrs": "string"}, crs, "LineString")


def _transfer_rows(transfers, stops, network):
    for record in transfers:
        incoming, outgoing = record.connection.incoming, record.connection.outgoing
        if incoming.stop_id not in stops or outgoing.stop_id not in stops:
            raise ValueError("Transfer references an absent stop")
        walk = record.walk
        if walk and network is not None:
            if (any(n not in network for n in walk.node_ids)
                    or any(not network.has_edge(u, v) for u, v in pairwise(walk.node_ids))):
                raise ValueError("Walking route references an absent node or directed edge")
        vertices = walk.geometry if walk else ()
        yield (incoming.stop_id, outgoing.stop_id, incoming.route_id, outgoing.route_id,
               incoming.direction_id, outgoing.direction_id,
               record.service_date.isoformat() if record.service_date else None,
               record.walking_speed_mps, walk.distance_meters if walk else None,
               walk.duration_seconds if walk else None, json.dumps(walk.node_ids) if walk else None,
               json.dumps(vertices[0]) if len(vertices) == 1 else None,
               LineString(vertices) if len(vertices) > 1 else None)


_TRANSFER_FIELDS = {"from_stop_id": "string", "to_stop_id": "string", "from_route_id": "string",
                    "to_route_id": "string", "from_direction_id": "Int64", "to_direction_id": "Int64",
                    "service_date": "string", "walking_speed_mps": "float64", "distance_m": "float64",
                    "duration_s": "float64", "node_ids": "string", "single_vertex": "string"}


def write_geopackage(path: str | Path, stops: Iterable[Stop], transfers: Iterable[StoredTransfer],
                     network: nx.MultiDiGraph | None = None) -> None:
    """Atomically replace a snapshot. Optional network uses integer OSM node and edge keys."""
    path = Path(path)
    points = {}
    for stop in stops:
        if stop.stop_id in points:
            raise ValueError(f"Duplicate stop ID: {stop.stop_id}")
        points[stop.stop_id] = stop
    with TemporaryDirectory(dir=path.parent) as staging:
        staged = Path(staging) / "snapshot.gpkg"
        rows = ((s.stop_id, s.name, Point(s.longitude, s.latitude)) for s in points.values())
        _write_layer(staged, "stops", rows, {"stop_id": "string", "stop_name": "string"},
                     WGS84, "Point")
        _write_layer(staged, "transfer_paths", _transfer_rows(transfers, points, network),
                     _TRANSFER_FIELDS, WGS84, "LineString")
        if network is not None:
            _write_network(staged, network)
        staged.replace(path)


def read_network(path):
    nodes = gpd.read_file(path, layer="pedestrian_nodes", engine="pyogrio")
    edges = gpd.read_file(path, layer="pedestrian_edges", engine="pyogrio")
    if nodes.crs is None or nodes.crs != edges.crs:
        raise ValueError("Pedestrian node and edge layers require a common CRS")
    metadata = read_info(path, layer="pedestrian_nodes")["layer_metadata"]
    graph = nx.MultiDiGraph()
    graph.graph.update(json.loads(metadata["graph_attrs"]), crs=nodes.crs)
    for row in nodes.itertuples():
        graph.add_node(row.node_id, x=row.geometry.x, y=row.geometry.y, **json.loads(row.attrs))
    for row in edges.itertuples():
        if row.u not in graph or row.v not in graph:
            raise ValueError("Pedestrian edge references an absent node")
        attrs = json.loads(row.attrs)
        attrs["length"] = row.length_m
        if row.has_shape:
            attrs["geometry"] = row.geometry
        graph.add_edge(row.u, row.v, key=row.edge_key)
        graph.edges[row.u, row.v, row.edge_key].update(attrs)
    return graph


def _read_transfers(frame):
    def leg(route, stop, direction):
        return TransferLeg(route, stop, None if pd.isna(direction) else int(direction))

    for row in frame.itertuples():
        connection = TransferConnection(leg(row.from_route_id, row.from_stop_id, row.from_direction_id),
                                        leg(row.to_route_id, row.to_stop_id, row.to_direction_id))
        walk = None
        if pd.notna(row.node_ids):
            vertices = tuple(row.geometry.coords) if row.geometry is not None else ()
            if pd.notna(row.single_vertex):
                vertices = (tuple(json.loads(row.single_vertex)),)
            walk = WalkingRoute(tuple(json.loads(row.node_ids)), row.distance_m, row.duration_s, vertices)
        day = date.fromisoformat(row.service_date) if pd.notna(row.service_date) else None
        yield StoredTransfer(connection, walk, day,
                             None if pd.isna(row.walking_speed_mps) else row.walking_speed_mps)


def read_stops(path):
    points = gpd.read_file(path, layer="stops", engine="pyogrio")
    if points.crs != WGS84:
        raise ValueError("Stops require WGS84 coordinates")
    return {r.stop_id: Stop(r.stop_id, r.stop_name, r.geometry.y, r.geometry.x)
            for r in points.itertuples()}


def append_cached_transfer(path, key, record, stops):
    row, = _transfer_rows([record], stops, None)
    _write_layer(path, "transfer_paths", [(*row[:-1], key, row[-1])],
                 {**_TRANSFER_FIELDS, "query_key": "string"}, WGS84, "LineString", append=True)


def read_cached_transfer(path, fid):
    frame = gpd.read_file(path, layer="transfer_paths", engine="pyogrio", fids=[fid])
    record, = _read_transfers(frame)
    return record


def read_geopackage(path: str | Path) -> SpatialSnapshot:
    """Restore stops, connections, walks and the optional routable graph."""
    layers = set(gpd.list_layers(path)["name"])
    graph_layers = {"pedestrian_nodes", "pedestrian_edges"}
    if layers & graph_layers and not graph_layers <= layers:
        raise ValueError("Incomplete pedestrian network in GeoPackage")
    paths = gpd.read_file(path, layer="transfer_paths", engine="pyogrio")
    if paths.crs != WGS84:
        raise ValueError("Transfer paths require WGS84 coordinates")
    return SpatialSnapshot(read_stops(path), list(_read_transfers(paths)),
                           read_network(path) if graph_layers <= layers else None)
