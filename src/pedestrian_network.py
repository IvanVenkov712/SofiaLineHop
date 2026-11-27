"""Locally cached WGS84 walking graphs and stop-to-stop pedestrian routes."""

from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha256
from itertools import pairwise
from math import isfinite
from operator import itemgetter
from pathlib import Path
from tempfile import NamedTemporaryFile

import networkx as nx
import osmnx as ox

from .models import Stop, WalkingRoute


def graphml_path(cache_dir: str | Path, place: str = "Sofia, Bulgaria") -> Path:
    key = sha256(place.strip().casefold().encode()).hexdigest()
    return Path(cache_dir) / f"{key}.graphml"


def build_pedestrian_network(
    place: str = "Sofia, Bulgaria",
    *,
    cache_dir: str | Path = Path("data/processed/pedestrian"),
    refresh: bool = False,
) -> nx.MultiDiGraph:
    """Load a cached GraphML graph, or fetch and cache all walking components."""
    directory = Path(cache_dir)
    path = graphml_path(directory, place)
    if path.is_file() and not refresh:
        return ox.load_graphml(path)

    graph = ox.graph_from_place(place, network_type="walk", retain_all=True)
    directory.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=directory, suffix=".graphml", delete=False) as temp:
        temporary_path = Path(temp.name)
    try:
        ox.save_graphml(graph, temporary_path)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return graph


def associate_stops(
    network: nx.MultiDiGraph, stops: Sequence[Stop], *, max_snap_distance_m: float | None = None
) -> tuple[int | None, ...]:
    """Snap stops to WGS84 graph nodes in input order. Unmatched stops yield None."""
    if max_snap_distance_m is not None and (
        not isfinite(max_snap_distance_m) or max_snap_distance_m < 0
    ):
        raise ValueError("max_snap_distance_m must be finite and nonnegative")
    if not network or not stops:
        return (None,) * len(stops)
    nodes, distances = ox.distance.nearest_nodes(
        network, [s.longitude for s in stops], [s.latitude for s in stops], return_dist=True
    )
    return tuple(
        int(node) if max_snap_distance_m is None or distance <= max_snap_distance_m else None
        for node, distance in zip(nodes, distances)
    )


def find_walking_route(
    network: nx.MultiDiGraph,
    origin: Stop,
    destination: Stop,
    walking_speed_mps: float,
    *,
    max_snap_distance_m: float | None = None,
) -> WalkingRoute | None:
    """Route between snapped nodes, excluding off-network access distances."""
    if not isfinite(walking_speed_mps) or walking_speed_mps <= 0:
        raise ValueError("walking_speed_mps must be finite and positive")
    start, end = associate_stops(network, (origin, destination), max_snap_distance_m=max_snap_distance_m)
    if start is None or end is None:
        return None
    try:
        distance, path = nx.single_source_dijkstra(network, start, end, weight="length")
    except nx.NetworkXNoPath:
        return None

    def coordinates(node: int) -> tuple[float, float]:
        data = network.nodes[node]
        return data["x"], data["y"]

    vertices = [coordinates(start)]
    for u, v in pairwise(path):
        edge = min(network[u][v].values(), key=itemgetter("length"))
        shape = edge.get("geometry")
        if shape is None:
            vertices.append(coordinates(v))
        else:
            points = list(shape.coords)
            if points[-1] == coordinates(u):
                points.reverse()
            vertices.extend(points[1:])
    return WalkingRoute(tuple(path), distance, distance / walking_speed_mps, tuple(vertices))
