"""Offline GTFS Realtime adapter tests using the official protobuf messages."""

from datetime import date, datetime
from io import BytesIO
from urllib.error import HTTPError

import pytest

from src import gtfs_realtime as rt
from src.models import Schedule, StopTime, Trip


DAY = date(2026, 11, 26)
ORIGIN = int(datetime(2026, 11, 26, tzinfo=rt.SOFIA).timestamp())
NOW = ORIGIN + 3600


@pytest.fixture
def feed():
    feed = rt.gtfs.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = NOW
    update = feed.entity.add(id="entity").trip_update
    update.trip.trip_id = "001"
    update.trip.route_id = "A1"
    update.timestamp = NOW - 12
    update.delay = -8
    visit = update.stop_time_update.add(stop_id="0001")
    visit.arrival.time = NOW + 95
    visit.arrival.delay = -7
    visit.arrival.uncertainty = 0
    visit.departure.delay = 0
    return feed


@pytest.fixture
def schedule():
    calls = (StopTime("0001", 10, 3700, 3710), StopTime("loop", 20, 4000, 4000),
             StopTime("loop", 30, 4100, 4100))
    return Schedule(DAY, {}, {}, (Trip("001", "A1", None, calls),))


def snapshot(feed):
    return rt.Snapshot(feed.SerializeToString(), NOW + 1)


def test_fetch_archive_and_match(feed, schedule, monkeypatch, tmp_path):
    payload = feed.SerializeToString()
    def open_feed(url, timeout):
        assert url == rt.TRIP_UPDATES_URL and timeout == 3
        return BytesIO(payload)

    monkeypatch.setattr(rt, "urlopen", open_feed)
    monkeypatch.setattr(rt.time, "time", lambda: NOW + 1)
    current = rt.fetch_snapshot(timeout=3)
    path = tmp_path / "experiment.json"
    current.save(path)
    replay = rt.Snapshot.load(path)
    assert replay == current
    assert replay.source_timestamp == NOW and replay.retrieved_at == NOW + 1
    updates, issues = rt.match_updates(replay, schedule)
    assert not issues
    trip = updates["001"]
    assert (trip.timestamp, trip.delay_seconds) == (NOW - 12, -8)
    visit, = trip.visits
    assert (visit.stop_id, visit.stop_sequence) == ("0001", 10)
    assert visit.arrival == rt.Prediction(NOW + 95, -5, -7, 0, True)
    assert visit.departure == rt.Prediction(NOW + 110, 0, 0, None, False)
    with pytest.raises(rt.RealtimeError, match="Stale"):
        rt.match_updates(replay, schedule, as_of=NOW + 100)


def test_partial_and_ambiguous_records(feed, schedule):
    update = feed.entity[0].trip_update
    update.stop_time_update[0].ClearField("departure")
    update.stop_time_update.add(stop_id="loop").arrival.time = NOW
    update.stop_time_update.add(stop_sequence=20, stop_id="wrong").arrival.time = NOW
    update.stop_time_update.add(stop_sequence=20, schedule_relationship=rt.gtfs.TripUpdate.StopTimeUpdate.SKIPPED)
    update.stop_time_update.add(stop_sequence=30, schedule_relationship=rt.gtfs.TripUpdate.StopTimeUpdate.NO_DATA)
    feed.entity.add(id="unknown").trip_update.trip.trip_id = "002"
    updates, issues = rt.match_updates(snapshot(feed), schedule)
    visits = updates["001"].visits
    assert [(v.stop_sequence, v.relationship) for v in visits] == [(10, "SCHEDULED"), (20, "SKIPPED"), (30, "NO_DATA")]
    assert visits[0].departure is None
    assert len(issues) == 3


@pytest.mark.parametrize("problem", ["old", "wrong_day", "route", "duplicate", "unknown", "missing_events"])
def test_invalid_trip(feed, schedule, problem):
    update = feed.entity[0].trip_update
    if problem == "old":
        update.timestamp = NOW - 100
    elif problem == "wrong_day":
        update.trip.start_date = "20261125"
    elif problem == "route":
        update.trip.route_id = "B"
    elif problem == "duplicate":
        feed.entity.add(id="other").trip_update.CopyFrom(update)
    elif problem == "unknown":
        update.trip.trip_id = "missing"
    else:
        update.ClearField("stop_time_update")
    updates, issues = rt.match_updates(snapshot(feed), schedule)
    assert issues and not updates


def test_canceled_trip(feed, schedule):
    update = feed.entity[0].trip_update
    update.trip.schedule_relationship = rt.gtfs.TripDescriptor.CANCELED
    update.ClearField("stop_time_update")
    updates, issues = rt.match_updates(snapshot(feed), schedule)
    assert not issues
    assert updates["001"].relationship == "CANCELED" and not updates["001"].visits


@pytest.mark.parametrize("failure", [TimeoutError(), HTTPError(rt.TRIP_UPDATES_URL, 503, "Unavailable", {}, None)])
def test_network_failure(monkeypatch, failure):
    def unavailable(*args, **kwargs):
        raise failure
    monkeypatch.setattr(rt, "urlopen", unavailable)
    with pytest.raises(rt.RealtimeError, match="unavailable"):
        rt.fetch_snapshot()


def test_invalid_snapshot(feed, tmp_path):
    with pytest.raises(rt.RealtimeError):
        rt.Snapshot(b"invalid", NOW)
    feed.header.incrementality = rt.gtfs.FeedHeader.DIFFERENTIAL
    with pytest.raises(rt.RealtimeError, match="FULL_DATASET"):
        snapshot(feed)
    path = tmp_path / "bad.json"
    path.write_text("{}")
    with pytest.raises(rt.RealtimeError, match="Invalid snapshot"):
        rt.Snapshot.load(path)

def test_undated_future_overnight_trip(feed):
    arrival = 24 * 3600 + 600
    feed.header.timestamp = ORIGIN + 23 * 3600
    update = feed.entity[0].trip_update
    update.timestamp = feed.header.timestamp
    update.stop_time_update[0].arrival.time = ORIGIN + arrival - 5
    snap = rt.Snapshot(feed.SerializeToString(), feed.header.timestamp)
    trip = Trip("001", "A1", None, (StopTime("0001", 10, arrival, arrival),))
    matched, issues = rt.match_updates(snap, Schedule(DAY, {}, {}, (trip,)))
    assert not issues and matched["001"].visits[0].arrival.delay_seconds == -5
    other, issues = rt.match_updates(snap, Schedule(date(2026, 11, 27), {}, {}, (trip,)))
    assert not other and issues
