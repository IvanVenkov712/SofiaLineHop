from copy import deepcopy
from datetime import date

import pytest

from src.models import (
    Schedule, SimulationParameters, StopTime, TransferConnection, TransferLeg, Trip, WalkingRoute,
)
from src.optimization import evaluate_offsets, optimize_offsets
from src.simulation import DelayModel


def connection_inputs(arrivals, departures):
    trips = [
        Trip(f"in-{i}", "in", 0, (StopTime("A", 1, time, None),))
        for i, time in enumerate(arrivals)
    ] + [
        Trip(f"out-{i}", "out", 0, (StopTime("B", 1, None, time),))
        for i, time in enumerate(departures)
    ]
    # Other departures at the same stop cannot serve this connection.
    trips.extend([
        Trip("wrong-route", "other", 0, (StopTime("B", 1, None, 90),)),
        Trip("wrong-direction", "out", 1, (StopTime("B", 1, None, 90),)),
    ])
    return (Schedule(date(2026, 11, 23), {}, {}, tuple(trips)),
            TransferConnection(TransferLeg("in", "A", 0), TransferLeg("out", "B", 0)),
            WalkingRoute((), 0, 0), SimulationParameters(10, 100))


def test_shorter_wait_cannot_win_by_losing_an_attempt():
    args = connection_inputs([20, 90], [30, 95])
    original = deepcopy(args)
    result = optimize_offsets(*args, min_offset_seconds=-10, max_offset_seconds=-5,
                              step_seconds=5)
    assert set(result.scenarios) == {-10, -5, 0}
    assert result.scenarios[-10].mean_waiting_seconds == 0
    assert result.scenarios[-10].incomplete_rate == 0.5
    assert result.scenarios[0].mean_waiting_seconds == 7.5
    assert result.best_offset_seconds == -5
    assert args == original


def test_criterion_and_boundary_crossings():
    args = connection_inputs([10, 90], [5, 20, 100])
    scenarios = evaluate_offsets(*args, [-1, 5, 0, 5])
    assert set(scenarios) == {-1, 0, 5}
    assert scenarios[5].mean_waiting_seconds == 0
    assert scenarios[-1].successful_rate == 1
    assert scenarios[0].successful_rate == 0.5
    grid = dict(min_offset_seconds=-1, max_offset_seconds=5)
    assert optimize_offsets(*args, **grid).best_offset_seconds == 5
    assert optimize_offsets(*args, **grid, criterion="successful_rate").best_offset_seconds == -1


@pytest.mark.parametrize("seed", [None, 17])
def test_paired_draws_survive_window_changes(seed):
    args = connection_inputs([30], [8, 50])
    options = dict(arrival_delay=DelayModel(0, 5), departure_delay=DelayModel(0, 5),
                   repetitions=50, seed=seed)
    metrics = evaluate_offsets(*args, [5], **options)
    assert metrics[0].waiting_std_seconds > 0
    assert metrics[5].mean_waiting_seconds == pytest.approx(metrics[0].mean_waiting_seconds + 5)
    assert metrics[5].waiting_std_seconds == pytest.approx(metrics[0].waiting_std_seconds)
    if seed is not None:
        assert evaluate_offsets(*args, [5], **options) == metrics


@pytest.mark.parametrize("arrivals, departures", [([], [20]), ([20], []), ([20], [5])])
def test_undefined_mean_defaults_to_original(arrivals, departures):
    result = optimize_offsets(*connection_inputs(arrivals, departures),
                              min_offset_seconds=-1, max_offset_seconds=1)
    assert result.best_offset_seconds == 0


@pytest.mark.parametrize("minimum, maximum, step, criterion", [
    (1, 0, 1, "successful_rate"), (0, 2, 0, "successful_rate"),
    (0, 2, 0.5, "successful_rate"), (0, 2, 1, "unknown"),
])
def test_invalid_search_configuration(minimum, maximum, step, criterion):
    with pytest.raises(ValueError):
        optimize_offsets(*connection_inputs([], []), min_offset_seconds=minimum,
                         max_offset_seconds=maximum, step_seconds=step, criterion=criterion)
