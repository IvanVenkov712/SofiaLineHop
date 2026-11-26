"""Smoke check that component entry points can be imported before data is available."""

from src.analytics import summarize_transfers
from src.gtfs_loader import load_schedule
from src.optimization import evaluate_offsets
from src.pedestrian_network import build_pedestrian_network, find_walking_route
from src.simulation import simulate_transfers
from src.transfers import find_transfers


def test_public_entry_points():
    assert all(callable(entry_point) for entry_point in (
        load_schedule,
        build_pedestrian_network,
        find_walking_route,
        find_transfers,
        simulate_transfers,
        summarize_transfers,
        evaluate_offsets,
    ))
