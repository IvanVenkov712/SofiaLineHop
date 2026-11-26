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

def test_integrated_delay_propagation_and_coverage(feed):
    from src.realtime_schedule import integrate_schedule

    calls = tuple(StopTime("loop", n, 3600 + 60*n, 3610 + 60*n) for n in range(1, 10))
    trip = Trip("001", "A1", None, calls)
    static = Schedule(DAY, {}, {}, (trip, Trip("other", "B", None, calls[:1])))
    update = feed.entity[0].trip_update
    update.ClearField("stop_time_update")
    update.stop_time_update.add(stop_sequence=2).arrival.delay = 25
    update.stop_time_update.add(stop_sequence=3, schedule_relationship=1)  # SKIPPED
    update.stop_time_update.add(stop_sequence=5, schedule_relationship=2)  # NO_DATA
    update.stop_time_update.add(stop_sequence=7).departure.delay = -6
    update.stop_time_update.add(stop_sequence=9).departure.delay = 0
    view = integrate_schedule(static, snapshot(feed))
    assert not view.issues
    visits = view.trips["001"].visits
    assert [v.arrival.delay_seconds for v in visits] == [-8, 25, None, 25, None, None, None, -6, None]
    assert [v.departure.delay_seconds for v in visits] == [-8, 25, None, 25, None, None, -6, -6, 0]
    assert visits[1].arrival.source == "reported" and visits[1].departure.source == "propagated"
    assert visits[2].arrival.effective_seconds is None and not visits[2].can_board
    assert visits[3].can_board
    assert visits[5].relationship == "NO_DATA"
    assert visits[5].departure.updated_seconds is None
    assert visits[5].departure.effective_seconds == calls[5].departure_seconds
    assert visits[7].departure.updated_seconds == calls[7].departure_seconds - 6
    assert view.trips["other"].visits[0].arrival.source == "scheduled_fallback"
    coverage = view.coverage()
    assert (coverage.matched_trips, coverage.total_trips) == (1, 2)
    assert (coverage.reported_events, coverage.propagated_events, coverage.suppressed_events,
            coverage.fallback_events, coverage.total_events) == (3, 7, 2, 8, 20)
    assert coverage.timing_fraction == .5 and view.coverage("B").timing_fraction == 0
    assert view.coverage("unknown").trip_fraction is None
    assert view.baseline == static
    with pytest.raises(TypeError):
        view.baseline.routes["A1"] = None
    assert trip.stop_times == calls
    feed.ClearField("entity")
    empty = integrate_schedule(static, snapshot(feed))
    assert empty.coverage().fallback_events == 20 and view.coverage() == coverage


@pytest.mark.parametrize("relationship", ["CANCELED", "DELETED"])
def test_integrated_cancellation(feed, schedule, relationship):
    from src.realtime_schedule import integrate_schedule

    feed.entity[0].trip_update.trip.schedule_relationship = rt.gtfs.TripDescriptor.ScheduleRelationship.Value(relationship)
    view = integrate_schedule(schedule, snapshot(feed))
    assert all(v.relationship == relationship and not v.can_alight and not v.can_board
               and v.departure.effective_seconds is None for v in view.trips["001"].visits)
    assert view.coverage().suppressed_events == 6


@pytest.mark.parametrize("day", [date(2026, 3, 29), date(2026, 10, 25)])
def test_overnight_delay_only_on_clock_change(feed, day):
    from src.realtime_schedule import integrate_schedule

    noon = datetime.combine(day, datetime.min.time(), rt.SOFIA).replace(hour=12)
    origin = int(noon.timestamp()) - 43200
    seconds = 25 * 3600
    trip = Trip("001", "A1", None, (StopTime("0001", 10, seconds, seconds),))
    update = feed.entity[0].trip_update
    feed.header.timestamp = update.timestamp = origin + seconds
    update.ClearField("delay")
    visit = update.stop_time_update[0]
    visit.ClearField("arrival")
    visit.departure.delay = -10
    snap = rt.Snapshot(feed.SerializeToString(), feed.header.timestamp)
    view = integrate_schedule(Schedule(day, {}, {}, (trip,)), snap)
    assert not view.issues
    assert view.trips["001"].visits[0].departure.updated_seconds == seconds - 10
    visit.departure.time = origin + seconds + 12
    snap = rt.Snapshot(feed.SerializeToString(), feed.header.timestamp)
    event = integrate_schedule(Schedule(day, {}, {}, (trip,)), snap).trips["001"].visits[0].departure
    assert event.updated_seconds == seconds + 12 and event.delay_seconds == 12


def test_untimed_visit_absolute_prediction(feed):
    from src.realtime_schedule import integrate_schedule

    trip = Trip("001", "A1", None, (StopTime("first", 1, 3500, 3500),
                                    StopTime("0001", 10, None, None), StopTime("end", 20, 4000, 4000)))
    update = feed.entity[0].trip_update
    update.trip.start_date = DAY.strftime("%Y%m%d")
    update.stop_time_update[0].ClearField("departure")
    view = integrate_schedule(Schedule(DAY, {}, {}, (trip,)), snapshot(feed))
    visit = view.trips["001"].visits[1]
    assert visit.arrival.updated_seconds == 3695 and visit.arrival.delay_seconds is None
    assert visit.departure.source == "unavailable" and view.coverage().unavailable_events == 1
    assert view.trips["001"].visits[2].arrival.source == "scheduled_fallback"

def test_match_trip_descriptor_without_trip_id(feed):
    from src.realtime_schedule import integrate_schedule

    update = feed.entity[0].trip_update
    update.trip.ClearField("trip_id")
    update.trip.direction_id = 0
    update.trip.start_date = "20261126"
    update.trip.start_time = "01:01:50"
    update.stop_time_update[0].departure.time = NOW + 110
    calls = (StopTime("0001", 1, 3700, 3710),)
    trip = Trip("001", "A1", 0, calls)
    view = integrate_schedule(Schedule(DAY, {}, {}, (trip,)), snapshot(feed))
    assert not view.issues and view.coverage().reported_events == 2
    other = Trip("002", "A1", 0, calls)
    ambiguous = integrate_schedule(Schedule(DAY, {}, {}, (trip, other)), snapshot(feed))
    assert ambiguous.issues and ambiguous.coverage().matched_trips == 0
    update.trip.trip_id = "001"
    update.trip.start_time = "01:02:00"
    mismatch = integrate_schedule(Schedule(DAY, {}, {}, (trip,)), snapshot(feed))
    assert mismatch.issues and mismatch.coverage().matched_trips == 0
