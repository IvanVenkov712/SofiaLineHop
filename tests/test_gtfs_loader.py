from datetime import date

import pytest

from src.gtfs_loader import GTFSValidationError, load_schedule

MONDAY = date(2026, 11, 23)
TUESDAY = date(2026, 11, 24)


@pytest.fixture
def feed(tmp_path):
    tables = {
        "stops": 'stop_id,stop_name,stop_lat,stop_lon\n001,"Square, Sofia",42.7,23.3\n002,Park,42.6,23.4',
        "routes": "route_id,route_short_name\n01,72",
        "trips": "trip_id,service_id,route_id,direction_id\n01,weekly,01,0\n02,special,01,1",
        "stop_times": (
            "trip_id,stop_id,stop_sequence,arrival_time,departure_time,timepoint\n"
            "01,002,30,25:00:00,25:00:00,1\n02,002,1,7:00:00,7:01:00,1\n"
            "01,001,10,23:58:00,24:01:00,1\n01,001,20,,,0"
        ),
        "calendar": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            "weekly,1,1,0,0,0,0,0,20261123,20261130"
        ),
        "calendar_dates": "service_id,date,exception_type\nweekly,20261124,2\nspecial,20261124,1",
    }
    for name, content in tables.items():
        (tmp_path / f"{name}.txt").write_text(content + "\n", encoding="utf-8-sig")
    return tmp_path


def test_schedule_records(feed):
    schedule = load_schedule(feed, MONDAY)
    assert schedule.service_date == MONDAY
    assert schedule.stops["001"].name == "Square, Sofia"
    assert schedule.stops["002"].longitude == 23.4
    assert schedule.routes["01"].short_name == "72"
    trip, = schedule.trips
    assert (trip.trip_id, trip.route_id, trip.direction_id) == ("01", "01", 0)
    assert [(s.stop_id, s.stop_sequence, s.arrival_seconds, s.departure_seconds)
            for s in trip.stop_times] == [
        ("001", 10, 86280, 86460), ("001", 20, None, None), ("002", 30, 90000, 90000)
    ]


def test_unnamed_station_nodes_and_boarding_areas(feed):
    (feed / "stops.txt").write_text(
        "stop_id,stop_name,stop_lat,stop_lon,location_type\n"
        "001,Square,42.7,23.3,0\n002,Park,42.6,23.4,0\n"
        "node,,42.7,23.3,3\narea,,42.6,23.4,4\n"
    )
    assert len(load_schedule(feed, MONDAY).trips) == 1


@pytest.mark.parametrize(("day", "expected"), [
    (TUESDAY, ["02"]), (date(2026, 11, 25), []), (date(2026, 11, 30), ["01"]),
    (date(2026, 11, 16), []), (date(2026, 12, 7), []),
])
def test_service_dates(feed, day, expected):
    assert [t.trip_id for t in load_schedule(feed, day).trips] == expected


def test_calendar_dates_only_and_optional_direction(feed):
    (feed / "calendar.txt").unlink()
    (feed / "trips.txt").write_text("trip_id,service_id,route_id\n02,special,01\n")
    (feed / "stop_times.txt").write_text(
        "trip_id,stop_id,stop_sequence,arrival_time,departure_time\n02,001,0,0:00:00,0:00:00\n"
    )
    assert not load_schedule(feed, MONDAY).trips
    trip, = load_schedule(feed, TUESDAY).trips
    assert trip.direction_id is None
    assert trip.stop_times[0].arrival_seconds == 0


def test_weekly_calendar_only(feed):
    (feed / "calendar_dates.txt").write_text("service_id,date,exception_type\nspecial,20261125,1\n")
    assert load_schedule(feed, TUESDAY).trips[0].trip_id == "01"
    (feed / "calendar_dates.txt").unlink()
    path = feed / "trips.txt"
    path.write_text(path.read_text(encoding="utf-8-sig").replace("special", "weekly"))
    assert len(load_schedule(feed, TUESDAY).trips) == 2


def test_half_open_overnight_window(feed):
    trip, = load_schedule(feed, MONDAY, start_seconds=86460, end_seconds=90000).trips
    assert [s.stop_sequence for s in trip.stop_times] == [10]
    trip, = load_schedule(feed, MONDAY, start_seconds=90000).trips
    assert [s.stop_sequence for s in trip.stop_times] == [30]
    assert not load_schedule(feed, MONDAY, end_seconds=86280).trips
    with pytest.raises(ValueError, match="start"):
        load_schedule(feed, MONDAY, start_seconds=86400, end_seconds=3600)


@pytest.mark.parametrize(("table", "old", "new", "message"), [
    ("calendar", "20261123", "20260230", "day"),
    ("calendar", "1,1,0", "1,3,0", "weekday"),
    ("calendar_dates", "20261124,2", "20261124,3", "exception_type"),
    ("calendar_dates", "special,20261124", "weekly,20261124", "duplicate"),
    ("stops", "42.7", "nan", "coordinates"),
    ("stops", "002,Park", "001,Park", "duplicate"),
    ("stops", "002,Park", "002,", "stop_name"),
    ("stops", "stop_lat", "latitude", "missing columns"),
    ("routes", "01,72", "01,", "route name"),
    ("trips", "weekly,01,0", "missing,01,0", "service_id"),
    ("trips", "weekly,01,0", "weekly,missing,0", "route_id"),
    ("trips", "special,01,1", "special,01,2", "direction_id"),
    ("stop_times", "02,002", "02,missing", "stop_id"),
    ("stop_times", "02,002", "missing,002", "trip_id"),
    ("stop_times", "001,20", "001,10", "duplicate"),
    ("stop_times", "25:00:00", "25:60:00", "GTFS time"),
    ("stop_times", "25:00:00", "00:00:00", "times decrease"),
    ("stop_times", "23:58:00,", ",", "supplied together"),
    ("stop_times", "25:00:00,25:00:00,1", ",,0", "timed first and last"),
    ("stop_times", "001,20,,,0", "001,20,,", "number of fields"),
])
def test_invalid_feed(feed, table, old, new, message):
    path = feed / f"{table}.txt"
    path.write_text(path.read_text(encoding="utf-8-sig").replace(old, new))
    with pytest.raises(GTFSValidationError, match=message) as error:
        load_schedule(feed, MONDAY)
    assert path.name in str(error.value)


def test_missing_tables(feed):
    (feed / "calendar.txt").unlink()
    (feed / "calendar_dates.txt").unlink()
    with pytest.raises(GTFSValidationError, match="calendar_dates.txt"):
        load_schedule(feed, MONDAY)
    (feed / "stops.txt").unlink()
    with pytest.raises(FileNotFoundError, match="stops.txt"):
        load_schedule(feed, MONDAY)
