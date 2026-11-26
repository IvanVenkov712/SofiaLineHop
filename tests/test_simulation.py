from datetime import date

import pytest

from src.models import (
    Schedule, SimulationParameters, StopTime, TransferConnection, TransferLeg,
    TransferOutcome, Trip, WalkingRoute,
)
from src.simulation import DelayModel, simulate_stochastic_transfers, simulate_transfers


def scenario(arrivals, departures, walk=0, buffer=0, start=0, end=100):
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
    return schedule, connection, WalkingRoute((), 0, walk), SimulationParameters(start, end, buffer)


def simulate(*args, **kwargs):
    return simulate_transfers(*scenario(*args, **kwargs))


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


def test_zero_delays_match_scheduled_results_in_every_run():
    args = scenario([("a", 10), ("b", 99)], [("bus", 16)], walk=3.5, buffer=2)
    scheduled = simulate_transfers(*args)
    runs = simulate_stochastic_transfers(*args, repetitions=3, seed=42)
    assert len(runs) == 3
    for first, last in runs:
        assert [first.transfer, last.transfer] == scheduled
        assert first.missed_intended_connection is False
        assert last.missed_intended_connection is None


def test_missed_intention_with_and_without_an_in_window_alternative():
    args = scenario([("a", 10), ("b", 20)], [("intended", 15), ("later", 25)],
                    walk=2.5, buffer=1)
    first, last = simulate_stochastic_transfers(*args, arrival_delay=DelayModel(10, 10))[0]
    assert first.intended_departure.trip_id == "intended"
    assert first.missed_intended_connection is True
    assert first.transfer == TransferOutcome("a", "later", True, 2.5, 5, 10, 25)
    assert last.missed_intended_connection is True
    assert not last.transfer.successful


def test_departure_delayed_to_horizon_is_unavailable_even_when_passenger_is_ready():
    args = scenario([("a", 5)], [("bus", 90)])
    row, = simulate_stochastic_transfers(*args, departure_delay=DelayModel(10, 10))[0]
    assert row.missed_intended_connection is False
    assert not row.transfer.successful


def test_seed_replays_runs_and_passengers_share_each_departure_draw():
    args = scenario([("a", 1), ("b", 1)], [("bus", 10)])
    def run(seed):
        return simulate_stochastic_transfers(*args, repetitions=12, seed=seed,
                                             arrival_delay=DelayModel(0, 3),
                                             departure_delay=DelayModel(0, 20))
    runs = run(42)
    assert runs == run(42)
    assert runs != run(43)
    assert len({row.actual_arrival_seconds for pair in runs for row in pair}) > 1
    departures = set()
    for pair in runs:
        times = {row.actual_arrival_seconds + row.transfer.total_duration_seconds for row in pair}
        assert len(times) == 1
        assert 10 <= times.pop() <= 30
        departures.add(pair[0].actual_arrival_seconds + pair[0].transfer.total_duration_seconds)
    assert len(departures) > 1


@pytest.mark.parametrize("bounds", [(-1, 2), (3, 2), (0, 1.5)])
def test_invalid_delay_bounds(bounds):
    with pytest.raises(ValueError):
        DelayModel(*bounds)


@pytest.mark.parametrize("count", [0, -1, 1.5, True])
def test_invalid_repetitions(count):
    with pytest.raises(ValueError, match="repetitions"):
        simulate_stochastic_transfers(*scenario([], []), repetitions=count)
