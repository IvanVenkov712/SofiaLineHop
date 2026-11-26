"""Read scheduled stop events from an unpacked GTFS feed."""

import csv
import re
from collections import defaultdict
from dataclasses import replace
from contextlib import contextmanager
from datetime import date
from functools import lru_cache
from pathlib import Path

from .models import Route, Schedule, Stop, StopTime, Trip


class GTFSValidationError(ValueError):
    """A feed cannot be represented as a valid schedule."""


_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_TIME = re.compile(r"([0-9]{1,2}):([0-5][0-9]):([0-5][0-9])")


@contextmanager
def _table(directory, name, columns, *, nullable=()):
    """Check CSV structure and attach source locations to field errors."""
    path = directory / name
    required_values = set(columns) - set(nullable)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)

        def records():
            for row in reader:
                if None in row or None in row.values():
                    raise ValueError("record has the wrong number of fields")
                for field in required_values:
                    if not row[field].strip():
                        raise ValueError(f"missing {field}")
                yield row

        try:
            headers = reader.fieldnames or []
            missing = set(columns) - set(headers)
            if missing:
                raise ValueError(f"missing columns {', '.join(sorted(missing))}")
            if len(headers) != len(set(headers)):
                raise ValueError("duplicate column name")
            yield records()
        except (ValueError, csv.Error) as exc:
            raise GTFSValidationError(f"{name} line {reader.line_num}: {exc}") from exc


@lru_cache(maxsize=2048)
def _date(value):
    if not re.fullmatch(r"[0-9]{8}", value):
        raise ValueError(f"invalid GTFS date {value!r}")
    return date(int(value[:4]), int(value[4:6]), int(value[6:]))


def _services(directory, day):
    known, active = set(), set()
    if (directory / "calendar.txt").is_file():
        with _table(directory, "calendar.txt", ("service_id", *_WEEKDAYS, "start_date", "end_date")) as rows:
            for row in rows:
                service = row["service_id"]
                _unique(known, service, "service_id")
                known.add(service)
                start, end = _date(row["start_date"]), _date(row["end_date"])
                if start > end or any(row[d] not in ("0", "1") for d in _WEEKDAYS):
                    raise ValueError("invalid service date range or weekday flag")
                if start <= day <= end and row[_WEEKDAYS[day.weekday()]] == "1":
                    active.add(service)
    elif not (directory / "calendar_dates.txt").is_file():
        raise GTFSValidationError("expected calendar.txt or calendar_dates.txt")

    if (directory / "calendar_dates.txt").is_file():
        seen_dates = defaultdict(set)
        with _table(directory, "calendar_dates.txt", ("service_id", "date", "exception_type")) as rows:
            for row in rows:
                service, on = row["service_id"], _date(row["date"])
                if on in seen_dates[service]:
                    raise ValueError(f"duplicate calendar exception {(service, on)!r}")
                seen_dates[service].add(on)
                known.add(service)
                kind = row["exception_type"]
                if kind not in ("1", "2"):
                    raise ValueError(f"invalid exception_type {kind!r}")
                if on == day:
                    if kind == "1":
                        active.add(service)
                    else:
                        active.discard(service)
    return known, active


def _unique(existing, key, field):
    if key in existing:
        raise ValueError(f"duplicate {field} {key!r}")


def _stops(directory):
    stops = {}
    with _table(directory, "stops.txt", ("stop_id", "stop_name", "stop_lat", "stop_lon"),
                nullable=("stop_name",)) as rows:
        for row in rows:
            key = row["stop_id"]
            _unique(stops, key, "stop_id")
            if not row["stop_name"].strip() and row.get("location_type") not in ("3", "4"):
                raise ValueError("missing stop_name")
            lat, lon = float(row["stop_lat"]), float(row["stop_lon"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError(f"invalid coordinates for stop {key!r}")
            stops[key] = Stop(key, row["stop_name"], lat, lon)
    return stops


def _routes(directory):
    routes = {}
    with _table(directory, "routes.txt", ("route_id",)) as rows:
        for row in rows:
            key = row["route_id"]
            _unique(routes, key, "route_id")
            short, long = row.get("route_short_name", ""), row.get("route_long_name", "")
            if not (short.strip() or long.strip()):
                raise ValueError(f"missing route name for {key!r}")
            routes[key] = Route(key, short, long)
    return routes


@lru_cache(maxsize=65536)
def parse_gtfs_time(value):
    if not value:
        return None
    match = _TIME.fullmatch(value)
    if not match:
        raise ValueError(f"invalid GTFS time {value!r}")
    hours, minutes, seconds = map(int, match.groups())
    return hours * 3600 + minutes * 60 + seconds


def load_schedule(gtfs_directory: Path, service_date: date, *,
                  start_seconds: int = 0, end_seconds: int | None = None) -> Schedule:
    """Load events for a service date, retaining calls with either time in [start, end).

    Bounds are seconds from the service-day origin, including values beyond 86400.
    With the default bounds, untimed intermediate stops are also retained.
    Raises FileNotFoundError for missing core tables and GTFSValidationError for
    invalid feed data. Validates inactive trips as well as active trips.
    """
    if start_seconds < 0 or (end_seconds is not None and end_seconds <= start_seconds):
        raise ValueError("expected a nonnegative start and an end greater than the start")
    directory = Path(gtfs_directory)
    stops, routes = _stops(directory), _routes(directory)
    known, active = _services(directory, service_date)
    trips = {}
    with _table(directory, "trips.txt", ("trip_id", "route_id", "service_id")) as rows:
        for row in rows:
            key, route, service = row["trip_id"], row["route_id"], row["service_id"]
            _unique(trips, key, "trip_id")
            if route not in routes or service not in known:
                raise ValueError(f"unknown route_id {route!r} or service_id {service!r}")
            direction = row.get("direction_id", "")
            if direction not in ("", "0", "1"):
                raise ValueError(f"invalid direction_id {direction!r}")
            trips[key] = (route, int(direction) if direction else None, service)

    calls = {key: {} for key in trips}
    times = ("arrival_time", "departure_time")
    with _table(directory, "stop_times.txt", ("trip_id", "stop_id", "stop_sequence", *times),
                nullable=times) as rows:
        for row in rows:
            key, stop = row["trip_id"], row["stop_id"]
            if key not in trips or stop not in stops:
                raise ValueError(f"unknown trip_id {key!r} or stop_id {stop!r}")
            if not re.fullmatch(r"[0-9]+", row["stop_sequence"]):
                raise ValueError(f"invalid stop_sequence {row['stop_sequence']!r}")
            sequence = int(row["stop_sequence"])
            _unique(calls[key], sequence, f"stop_sequence for trip {key!r}")
            arrival, departure = (parse_gtfs_time(row[field]) for field in times)
            if (arrival is None) != (departure is None):
                raise ValueError("arrival_time and departure_time must be supplied together")
            if arrival is None and row.get("timepoint") == "1":
                raise ValueError("missing times for an exact timepoint")
            calls[key][sequence] = StopTime(
                stops[stop].stop_id, sequence, arrival, departure,
                can_alight=row.get("drop_off_type") != "1",
                can_board=row.get("pickup_type") != "1",
            )

    result = []
    filtered = start_seconds != 0 or end_seconds is not None
    for key, (route, direction, service) in trips.items():
        trip_calls = calls.pop(key)
        ordered = [trip_calls[seq] for seq in sorted(trip_calls)]
        if not ordered or ordered[0].arrival_seconds is None or ordered[-1].departure_seconds is None:
            raise GTFSValidationError(f"stop_times.txt: trip {key!r} needs timed first and last stops")
        previous = 0
        # Preserve terminal restrictions even when a query clips the trip.
        ordered[0] = replace(ordered[0], can_alight=False)
        ordered[-1] = replace(ordered[-1], can_board=False)
        selected = []
        for call in ordered:
            arrival, departure = call.arrival_seconds, call.departure_seconds
            if arrival is not None:
                if not previous <= arrival <= departure:
                    raise GTFSValidationError(f"stop_times.txt: times decrease on trip {key!r} at {call.stop_sequence}")
                previous = departure
            if service in active and (not filtered or any(
                t is not None and t >= start_seconds and (end_seconds is None or t < end_seconds)
                for t in (arrival, departure)
            )):
                selected.append(call)
        if selected:
            result.append(Trip(key, route, direction, tuple(selected)))
    return Schedule(service_date, stops, routes, tuple(result))
