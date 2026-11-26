from datetime import date

import pytest

from src.models import (
    Schedule, SimulationParameters, StopTime, TransferConnection, TransferLeg,
    TransferOutcome, Trip, WalkingRoute,
)
from src.simulation import simulate_transfers


def simulate(arrivals, departures, walk=0, buffer=0, start=0, end=100):
    trips = [
        Trip(trip_id, "in", 0, (StopTime("A", 1, time, None),))
        for trip_id, time in arrivals
    ]
    trips.extend(
        Trip(trip_id, "out", 1, (StopTime("B", 1, None, time),))
        for trip_id, time in departures
    )
    schedule = Schedule(date(2026, 11, 23), {}, {}, tuple(trips))
    connection = TransferConnection(TransferLeg("in", "A", 0), TransferLeg("out", "B", 1))
    return simulate_transfers(
        schedule, connection, WalkingRoute((), 0, walk), SimulationParameters(start, end, buffer),
    )


def test_first_feasible_departure_for_each_arrival():
    outcomes = simulate(
        [("second", 11), ("first", 10), ("late", 91)],
        [("later", 40), ("b", 21), ("early", 19), ("a", 21)],
        walk=5.5, buffer=4,
    )
    assert outcomes == [
        TransferOutcome("first", "a", True, 5.5, 11, 10, 21),
        TransferOutcome("second", "a", True, 4.5, 10, 11, 21),
        TransferOutcome("late", None, False, None, None, 91, None),
    ]


def test_exact_walk_and_buffer_boundary_after_midnight():
    assert simulate([("i", 90000)], [("o", 90025)], walk=20, buffer=5,
                    start=90000, end=90026) == [
        TransferOutcome("i", "o", True, 5, 25, 90000, 90025),
    ]


def test_horizon_excludes_end_and_allows_immediate_transfer_at_start():
    assert simulate([("before", 9), ("i", 10), ("late", 19), ("end", 20)],
                    [("o", 10), ("next", 20)], start=10, end=20) == [
        TransferOutcome("i", "o", True, 0, 0, 10, 10),
        TransferOutcome("late", None, False, None, None, 19, None),
    ]


def test_empty_timetables():
    assert simulate([], [("o", 1)]) == []
    assert simulate([("i", 1)], []) == [
        TransferOutcome("i", None, False, None, None, 1, None),
    ]


@pytest.mark.parametrize(("walk", "buffer"), [(-1, 0), (float("nan"), 0), (float("inf"), 0), (0, -1)])
def test_invalid_durations(walk, buffer):
    with pytest.raises(ValueError, match="nonnegative"):
        simulate([], [], walk, buffer)
