"""Persistent cache for the Sofia spatial acquisition and routing workflow."""

import json
import logging
import sqlite3
from contextlib import closing
from dataclasses import astuple, dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import networkx as nx
from filelock import FileLock
from pyproj import CRS
from shapely.errors import GEOSException

from . import geopackage, pedestrian_network
from .models import TransferConnection, TransferLeg
from .transfers import find_transfers

DEFAULT_PACKAGE = Path(__file__).resolve().parents[1] / "data/processed/sofia_transport.gpkg"
SCHEMA_VERSION = 1
LOG = logging.getLogger(__name__)
_INVALID = (sqlite3.DatabaseError, ValueError, TypeError, AttributeError, KeyError,
            RuntimeError, GEOSException, OSError)


def file_stamp(path):
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def _manifest(path):
    if path.is_file():
        try:
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
                row = db.execute("SELECT version, generation, stops_stamp, graph_stamp FROM cache_info").fetchone()
                if row and row[0] == SCHEMA_VERSION:
                    db.execute("SELECT stop_id, stop_name, geom FROM stops LIMIT 0")
                    db.execute("SELECT node_id, attrs, geom FROM pedestrian_nodes LIMIT 0")
                    db.execute("SELECT u, v, edge_key, length_m, has_shape, attrs, geom FROM pedestrian_edges LIMIT 0")
                    db.execute("SELECT query_key, pairs FROM connection_searches LIMIT 0")
                    db.execute("SELECT query_key, from_route_id, to_route_id, from_stop_id, to_stop_id,"
                               " from_direction_id, to_direction_id, service_date, walking_speed_mps,"
                               " distance_m, duration_s, single_vertex, node_ids, geom FROM transfer_paths LIMIT 0")
                    return row
        except sqlite3.DatabaseError:
            pass
    return None


def cache_version(path):
    manifest = _manifest(Path(path).resolve())
    return manifest[1] if manifest else None


def cached_stops(path, stops_stamp):
    """Permit offline reuse when only the spatial source file was removed."""
    path = Path(path).resolve()
    manifest = _manifest(path)
    if manifest and (stops_stamp is None or stops_stamp == manifest[2]):
        try:
            return geopackage.read_stops(path)
        except _INVALID as exc:
            LOG.warning("Rebuilding unreadable cached stops: %s", exc)
    return None


def _key(*values):
    return sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


@dataclass
class SpatialCache:
    path: Path
    generation: str
    network: nx.MultiDiGraph

    def is_current(self):
        manifest = _manifest(self.path)
        graph_stamp = file_stamp(pedestrian_network.graphml_path(self.path.parent / "pedestrian"))
        return bool(manifest and manifest[1] == self.generation
                    and (graph_stamp is None or graph_stamp == manifest[3]))

    def connections(self, schedule, feed_version, incoming, outgoing, incoming_dir, outgoing_dir, limit, snap):
        key = _key(feed_version, schedule.service_date.isoformat(), incoming, outgoing,
                   incoming_dir, outgoing_dir, limit, snap)
        with FileLock(str(self.path) + ".lock"):
            current = cache_version(self.path) == self.generation
            if current:
                with closing(sqlite3.connect(self.path)) as db:
                    row = db.execute("SELECT pairs FROM connection_searches WHERE query_key=?", (key,)).fetchone()
                if row:
                    try:
                        return [TransferConnection(TransferLeg(incoming, a, incoming_dir),
                                                   TransferLeg(outgoing, b, outgoing_dir))
                                for a, b in json.loads(row[0])]
                    except (TypeError, ValueError):
                        LOG.warning("Recomputing unreadable connection search")
            pairs = find_transfers(schedule, limit, network=self.network, incoming_route_id=incoming,
                                   outgoing_route_id=outgoing, incoming_direction_id=incoming_dir,
                                   outgoing_direction_id=outgoing_dir, max_snap_distance_m=snap)
            if current:
                payload = json.dumps([(p.incoming.stop_id, p.outgoing.stop_id) for p in pairs])
                with closing(sqlite3.connect(self.path)) as db, db:
                    db.execute("INSERT OR REPLACE INTO connection_searches VALUES (?, ?)", (key, payload))
            return pairs

    def walking_route(self, schedule, pair, speed, snap):
        key = _key(schedule.service_date.isoformat(), astuple(pair), speed, snap)
        with FileLock(str(self.path) + ".lock"):
            current = cache_version(self.path) == self.generation
            if current:
                with closing(sqlite3.connect(self.path)) as db:
                    row = db.execute("SELECT fid FROM transfer_paths WHERE query_key=?", (key,)).fetchone()
                if row:
                    try:
                        return geopackage.read_cached_transfer(self.path, row[0]).walk
                    except _INVALID as exc:
                        LOG.warning("Recomputing unreadable walking route: %s", exc)
                        with closing(sqlite3.connect(self.path)) as db, db:
                            db.execute("DELETE FROM transfer_paths WHERE fid=?", row)
            walk = pedestrian_network.find_walking_route(
                self.network, schedule.stops[pair.incoming.stop_id], schedule.stops[pair.outgoing.stop_id],
                speed, max_snap_distance_m=snap)
            if current:
                record = geopackage.StoredTransfer(pair, walk, schedule.service_date, speed)
                geopackage.append_cached_transfer(self.path, key, record, schedule.stops)
            return walk


def load_spatial_cache(path, stops, stops_stamp):
    """Load a compatible generation or atomically publish a complete replacement."""
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    directory = path.parent / "pedestrian"
    graphml = pedestrian_network.graphml_path(directory)
    with FileLock(str(path) + ".lock"):
        manifest = _manifest(path)
        graph_stamp = file_stamp(graphml)
        graph = None
        if manifest and (graph_stamp is None or graph_stamp == manifest[3]):
            try:
                graph = geopackage.read_network(path)
                if graph.graph["crs"] != geopackage.WGS84:
                    raise ValueError("The routing workflow requires WGS84")
                if ((stops_stamp is None or stops_stamp == manifest[2])
                        and geopackage.read_stops(path) == stops):
                    return SpatialCache(path, manifest[1], graph)
            except _INVALID as exc:
                LOG.warning("Rebuilding incompatible spatial cache: %s", exc)
        if graph is None or graph.graph["crs"] != geopackage.WGS84:
            graph = pedestrian_network.build_pedestrian_network(cache_dir=directory)
            if CRS.from_user_input(graph.graph.get("crs")) != geopackage.WGS84:
                raise ValueError("The Sofia walking graph must use WGS84. Refresh the GraphML source.")
            graph_stamp = file_stamp(graphml)
        elif graph_stamp is None:
            graph_stamp = manifest[3]
        generation = uuid4().hex
        with TemporaryDirectory(dir=path.parent) as staging:
            staged = Path(staging) / path.name
            geopackage.write_geopackage(staged, stops.values(), [], graph)
            with closing(sqlite3.connect(staged)) as db, db:
                db.execute("CREATE TABLE cache_info (version INTEGER, generation TEXT, stops_stamp TEXT, graph_stamp TEXT)")
                db.execute("INSERT INTO cache_info VALUES (?, ?, ?, ?)",
                           (SCHEMA_VERSION, generation, stops_stamp or (manifest and manifest[2]), graph_stamp))
                db.execute("CREATE TABLE connection_searches (query_key TEXT PRIMARY KEY, pairs TEXT NOT NULL)")
                db.execute("ALTER TABLE transfer_paths ADD COLUMN query_key TEXT")
                db.execute("CREATE UNIQUE INDEX transfer_query ON transfer_paths(query_key)")
            staged.replace(path)
        return SpatialCache(path, generation, graph)
