"""Replay three paired experiments against the frozen Sofia inputs."""

import argparse
from datetime import date
from pathlib import Path

import osmnx as ox

from src.gtfs_loader import load_schedule
from src.gtfs_realtime import Snapshot
from src.models import SimulationParameters, TransferConnection, TransferLeg
from src.optimization import optimize_offsets
from src.pedestrian_network import find_walking_route
from src.realtime_schedule import integrate_schedule
from src.transfers import find_transfers


def main():
    inputs = Path("data/processed/demo-20261127")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static", type=Path, default=inputs / "gtfs")
    parser.add_argument("--graph", type=Path, default=inputs / "central-sofia.graphml")
    parser.add_argument("--snapshot", type=Path, default=inputs / "1795773766.json")
    args = parser.parse_args()
    static = load_schedule(args.static, date(2026, 11, 27))
    snapshot = Snapshot.load(args.snapshot)
    view = integrate_schedule(static, snapshot)
    graph = ox.load_graphml(args.graph)
    print(f"Feed {snapshot.source_timestamp}, retrieved {snapshot.retrieved_at}")
    print(view.coverage())
    for issue in view.issues:
        print(issue)

    # Compare operating conditions, add a fixed disturbance, then search offsets.
    for incoming, outgoing in [(("TM34", "TM1307"), ("M1", "M7")),
                               (("TB10", "TB0283"), ("TM27", "TM1269"))]:
        pair = TransferConnection(TransferLeg(*incoming), TransferLeg(*outgoing))
        pairs = find_transfers(static, 500, network=graph, incoming_route_id=incoming[0],
                               outgoing_route_id=outgoing[0], max_snap_distance_m=100)
        if pair not in pairs:
            raise ValueError(f"Could not recover reference connection {pair}")
        walk = find_walking_route(graph, static.stops[incoming[1]], static.stops[outgoing[1]],
                                  1.4, max_snap_distance_m=100)
        print(f"\n{incoming} to {outgoing}, walk {walk.distance_meters:.2f} m")
        for delay in (0, 120):
            params = SimulationParameters(12 * 3600 + 180, 13 * 3600, 30, delay)
            result = optimize_offsets(view, pair, walk, params, min_offset_seconds=-300,
                                      max_offset_seconds=300, step_seconds=60, seed=42)
            print(f"Extra incoming delay {delay} s; arrival sources {result.arrival_sources}; "
                  f"departure sources {result.departure_sources}")
            attempts = sum(result.arrival_sources.values())
            print("condition     offset_s  completed/attempts  mean_wait_s  intended_miss_rate")
            for label, offset, metrics in [("scheduled", 0, result.published_reference),
                                           ("realtime", 0, result.scenarios[0]),
                                           ("optimized", result.best_offset_seconds,
                                            result.scenarios[result.best_offset_seconds])]:
                completed = round(attempts * metrics.successful_rate)
                print(f"{label:10} {offset:10} {completed:9}/{attempts:<8} "
                      f"{metrics.mean_waiting_seconds:10.2f}  {metrics.missed_connection_rate:.3f}")


if __name__ == "__main__":
    main()
