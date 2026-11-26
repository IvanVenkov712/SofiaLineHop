"""Offline end-to-end forecasts for one transfer connection."""
from dataclasses import replace
from datetime import date, timedelta

import pytest

from src.analytics import summarize_transfers, summarize_transfers_by_interval
from src.gtfs_realtime import Snapshot, gtfs, service_day_origin
from src.models import Schedule, SimulationParameters, StopTime, TransferConnection, TransferLeg, Trip, WalkingRoute
from src.optimization import evaluate_offsets, optimize_offsets
from src.realtime_schedule import integrate_schedule
from src.simulation import DelayModel, simulate_stochastic_transfers, simulate_transfers


DAY = date(2026, 11, 26)
ORIGIN = service_day_origin(DAY)


def inputs(updates, *, calls=None, base=0):
    """updates maps trip IDs to signed deviations or service relationships."""
    calls = calls or [("i", "in", 100), ("o", "out", 110), ("later", "out", 140)]
    feed = gtfs.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = ORIGIN + base + 95
    trips = []
    for key, route, scheduled in calls:
        stop = route + "-stop"
        published = base + scheduled
        trips.append(Trip(key, route, 0, (StopTime(stop, 4, published, published),)))
        if key not in updates:
            continue
        update = feed.entity.add(id=key).trip_update
        update.trip.trip_id = key
        update.trip.start_date = DAY.strftime("%Y%m%d")
        value = updates[key]
        if value == "CANCELED":
            update.trip.schedule_relationship = gtfs.TripDescriptor.CANCELED
        else:
            visit = update.stop_time_update.add(stop_id=stop)
            if value == "SKIPPED":
                visit.schedule_relationship = gtfs.TripUpdate.StopTimeUpdate.SKIPPED
            else:
                visit.arrival.delay = visit.departure.delay = value
    schedule = Schedule(DAY, {}, {}, tuple(trips))
    view = integrate_schedule(schedule, Snapshot(feed.SerializeToString(), feed.header.timestamp))
    connection = TransferConnection(TransferLeg("in", "in-stop", 0), TransferLeg("out", "out-stop", 0))
    return view, connection, WalkingRoute((), 0, 0), SimulationParameters(base+80, base+220)


def test_published_forecast_and_counterfactual():
    view, pair, walk, params = inputs({"i": 15, "o": 2})
    original, = simulate_transfers(view.baseline, pair, walk, params)
    assert original.waiting_seconds == 10
    forecast, = simulate_transfers(view, pair, walk, params)
    assert forecast.transfer.waiting_seconds == 25 and forecast.departure_source == "scheduled_fallback"
    assert forecast.arrival_source == "reported" and forecast.missed_intended_connection
    result = optimize_offsets(view, pair, walk, params, min_offset_seconds=0, max_offset_seconds=5, step_seconds=5)
    assert result.published_reference.mean_waiting_seconds == 10
    assert result.best_offset_seconds == 5 and result.scenarios[5].mean_waiting_seconds == 2
    assert result.recommendation.offset_seconds == 5 and "later" in result.recommendation.action
    assert result.departure_sources == {"reported": 1, "scheduled_fallback": 1}
    params = replace(params, arrival_delay_seconds=1, departure_delay_seconds=3)
    options = dict(repetitions=3, seed=9, arrival_delay=DelayModel(2, 2), departure_delay=DelayModel(4, 4))
    runs = simulate_stochastic_transfers(view, pair, walk, params, outgoing_offset_seconds=5, **options)
    for row, in runs:
        assert row.modeled_arrival_seconds == 118
        assert row.modeled_departure_seconds == 124
        assert row.transfer.waiting_seconds == 6
    assert evaluate_offsets(view, pair, walk, params, [5], **options)[5].mean_waiting_seconds == 6


@pytest.mark.parametrize("status", ["CANCELED", "SKIPPED"])
def test_suppressed_visits_keep_attempts(status):
    args = inputs({"i": status, "o": status}, calls=[("i", "in", 100), ("second", "in", 101),
                                                      ("o", "out", 110), ("later", "out", 140)])
    first, second = simulate_transfers(*args)
    assert first.arrival_source == status and first.modeled_arrival_seconds is None
    assert not first.transfer.successful and first.missed_intended_connection is None
    assert second.transfer.outgoing_trip_id == "later" and second.missed_intended_connection
    assert second.intended_departure_source == status
    assert summarize_transfers([first, second]).successful_rate == .5
    assert summarize_transfers_by_interval([first, second], 60)[60].successful_rate == .5


def test_early_departure_moves_into_window_and_fallback_only_abstains():
    args = inputs({"o": -25}, calls=[("i", "in", 199), ("o", "out", 225)])
    row, = simulate_transfers(*args)
    assert row.transfer.waiting_seconds == 1 and row.modeled_departure_seconds == 200
    assert row.transfer.scheduled_departure_seconds == 225
    result = optimize_offsets(*inputs({}), min_offset_seconds=-10, max_offset_seconds=0)
    assert result.recommendation is None and result.arrival_sources == {"scheduled_fallback": 1}


def test_archive_window_uses_service_day_origin_after_midnight():
    view, pair, walk, params = inputs({"i": 3}, base=86400)
    row, = simulate_transfers(view, pair, walk, params)
    assert row.modeled_arrival_seconds == 86503
    wrong_day = replace(view, baseline=replace(view.baseline, service_date=DAY + timedelta(days=1)))
    for schedule, window in [(wrong_day, params), (view, SimulationParameters(80, 220)),
                             (view, replace(params, end_seconds=params.end_seconds + 3600))]:
        with pytest.raises(ValueError, match="window"):
            optimize_offsets(schedule, pair, walk, window, min_offset_seconds=0, max_offset_seconds=1)


def test_seeded_realtime_draws_paired_across_offsets():
    args = inputs({"i": 0, "o": 4})
    options = dict(seed=17, repetitions=60, arrival_delay=DelayModel(0, 3), departure_delay=DelayModel(0, 4))
    metrics = evaluate_offsets(*args, [3], **options)
    assert metrics == evaluate_offsets(*args, [3], **options)
    assert metrics[0].waiting_std_seconds > 0
    assert metrics[3].mean_waiting_seconds == pytest.approx(metrics[0].mean_waiting_seconds + 3)
