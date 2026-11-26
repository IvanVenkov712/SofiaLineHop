"""Sofia GTFS Realtime full snapshots and explicit updates to static stop visits."""

import base64
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, time as daytime, timedelta
from http.client import HTTPException
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
import time
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2 as gtfs

from .models import Schedule, Trip
from .gtfs_loader import parse_gtfs_time


TRIP_UPDATES_URL = "https://gtfs.sofiatraffic.bg/api/v1/trip-updates"
SOFIA = ZoneInfo("Europe/Sofia")


def service_day_origin(day):
    """Unix seconds at GTFS local noon minus twelve elapsed hours (DST safe)."""
    return int(datetime.combine(day, daytime(12), SOFIA).timestamp()) - 43200


class RealtimeError(ValueError):
    """A snapshot is unavailable, unreadable or unsuitable for use."""


def _feed(payload):
    try:
        feed = gtfs.FeedMessage.FromString(payload)
    except DecodeError as exc:
        raise RealtimeError("Invalid GTFS Realtime protobuf") from exc
    header = feed.header
    if (header.gtfs_realtime_version != "2.0"
            or header.incrementality != gtfs.FeedHeader.FULL_DATASET
            or not header.timestamp):
        raise RealtimeError("Expected a timestamped GTFS Realtime 2.0 FULL_DATASET")
    return feed


@dataclass(frozen=True)
class Snapshot:
    """Original protobuf and retrieval time, both retained across replays."""

    payload: bytes = field(repr=False)
    retrieved_at: int
    source_timestamp: int = field(init=False)

    def __post_init__(self):
        if type(self.retrieved_at) is not int or self.retrieved_at <= 0:
            raise RealtimeError("Invalid retrieval timestamp")
        timestamp = _feed(self.payload).header.timestamp
        if timestamp > self.retrieved_at:
            raise RealtimeError("Feed timestamp is later than retrieval")
        object.__setattr__(self, "source_timestamp", timestamp)

    def save(self, path: Path):
        """Atomically save one self-contained archive, including the original bytes."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, delete=False) as temp:
            name = Path(temp.name)
        try:
            name.write_text(json.dumps({
                "retrieved_at": self.retrieved_at,
                "protobuf": base64.b64encode(self.payload).decode("ascii"),
            }), encoding="utf-8")
            name.replace(path)
        finally:
            name.unlink(missing_ok=True)

    @classmethod
    def load(cls, path: Path):
        try:
            record = json.loads(Path(path).read_text(encoding="utf-8"))
            return cls(base64.b64decode(record["protobuf"], validate=True), record["retrieved_at"])
        except (ValueError, TypeError, KeyError) as exc:
            raise RealtimeError(f"Invalid snapshot {path}: {exc}") from exc


def fetch_snapshot(*, timeout: float = 10, max_age: int = 90) -> Snapshot:
    """Fetch one snapshot. A failed refresh raises without replacing any archive."""
    try:
        with urlopen(TRIP_UPDATES_URL, timeout=timeout) as response:
            payload = response.read()
    except (OSError, HTTPException) as exc:
        raise RealtimeError(f"Trip Updates unavailable: {exc}") from exc
    snapshot = Snapshot(payload, int(time.time()))
    _check_age(snapshot, snapshot.retrieved_at, max_age)
    return snapshot


def _check_age(snapshot, as_of, max_age):
    if max_age < 0 or as_of < snapshot.source_timestamp:
        raise RealtimeError("Invalid freshness interval")
    if as_of - snapshot.source_timestamp > max_age:
        raise RealtimeError("Stale Trip Updates snapshot")


def _optional(message, name):
    return getattr(message, name) if message.HasField(name) else None


@dataclass(frozen=True)
class Prediction:
    timestamp: int
    delay_seconds: int | None
    reported_delay: int | None
    uncertainty: int | None
    has_reported_time: bool


@dataclass(frozen=True)
class VisitUpdate:
    stop_id: str
    stop_sequence: int
    relationship: str
    arrival: Prediction | None
    departure: Prediction | None


@dataclass(frozen=True)
class TripUpdate:
    trip_id: str
    route_id: str
    timestamp: int | None
    relationship: str
    delay_seconds: int | None
    visits: tuple[VisitUpdate, ...]


def _prediction(event, scheduled):
    absolute = _optional(event, "time")
    delay = _optional(event, "delay")
    if absolute is None:
        if delay is None or scheduled is None:
            raise ValueError("event needs time or delay with a static time")
        absolute = scheduled + delay
    if absolute <= 0 or event.uncertainty < 0:
        raise ValueError("invalid event timestamp or uncertainty")
    return Prediction(absolute, absolute - scheduled if scheduled is not None else None,
                      delay, _optional(event, "uncertainty"), event.HasField("time"))


def _visits(update, trip: Trip, origin, issues):
    previous = -1
    visits = []
    for stop in update.stop_time_update:
        candidates = [call for call in trip.stop_times
                      if (not stop.stop_id or call.stop_id == stop.stop_id)
                      and (not stop.HasField("stop_sequence") or call.stop_sequence == stop.stop_sequence)]
        if (not stop.stop_id and not stop.HasField("stop_sequence")) or len(candidates) != 1:
            issues.append(f"{trip.trip_id}: ambiguous or unknown visit {stop.stop_id!r}")
            continue
        call = candidates[0]
        if call.stop_sequence <= previous:
            issues.append(f"{trip.trip_id}: duplicate or unordered sequence {call.stop_sequence}")
            continue
        previous = call.stop_sequence
        relationship = stop.ScheduleRelationship.Name(stop.schedule_relationship)
        events = {}
        for name, seconds in (("arrival", call.arrival_seconds), ("departure", call.departure_seconds)):
            events[name] = None
            if stop.HasField(name) and relationship == "SCHEDULED":
                try:
                    events[name] = _prediction(getattr(stop, name), origin + seconds if seconds is not None else None)
                except ValueError as exc:
                    issues.append(f"{trip.trip_id}/{previous} {name}: {exc}")
        if relationship == "SCHEDULED" and not any(events.values()):
            issues.append(f"{trip.trip_id}/{previous}: missing prediction")
            continue
        if relationship not in ("SCHEDULED", "SKIPPED", "NO_DATA"):
            issues.append(f"{trip.trip_id}/{previous}: unsupported {relationship}")
            continue
        if events["arrival"] and events["departure"] and events["departure"].timestamp < events["arrival"].timestamp:
            issues.append(f"{trip.trip_id}/{previous}: departure before arrival")
            continue
        visits.append(VisitUpdate(call.stop_id, previous, relationship, **events))
    return tuple(visits)


def match_updates(snapshot: Snapshot, schedule: Schedule, *, as_of: int | None = None,
                  max_age: int = 90) -> tuple[dict[str, TripUpdate], list[str]]:
    """Match explicitly reported updates against one full service-day Schedule.

    Freshness defaults to retrieval time for repeatable offline experiments.
    Supply current Unix seconds as as_of when reusing a cached snapshot live.
    """
    as_of = snapshot.retrieved_at if as_of is None else as_of
    _check_age(snapshot, as_of, max_age)
    feed = _feed(snapshot.payload)
    trips = {trip.trip_id: trip for trip in schedule.trips}
    entity_ids = Counter(entity.id for entity in feed.entity)
    # Multiple dated instances may legitimately share the static trip ID.
    day = schedule.service_date
    origin = service_day_origin(day)
    yesterday = service_day_origin(day - timedelta(days=1))
    tomorrow = service_day_origin(day + timedelta(days=1))
    matched, issues = {}, []
    duplicates = set()
    for entity in feed.entity:
        update = entity.trip_update
        descriptor = update.trip
        key = descriptor.trip_id
        trip = trips.get(key)
        if descriptor.HasField("start_time"):
            try:
                start = parse_gtfs_time(descriptor.start_time)
            except ValueError:
                start = None
            if start is None:
                issues.append(f"{entity.id}: invalid start time")
                continue
            if (not key and descriptor.start_date and descriptor.HasField("direction_id")
                    and descriptor.schedule_relationship == gtfs.TripDescriptor.SCHEDULED):
                if any(not stop.stop_id or
                       any(stop.HasField(name) and not getattr(stop, name).HasField("time")
                           for name in ("arrival", "departure"))
                       for stop in update.stop_time_update):
                    issues.append(f"{entity.id}: alternative matching requires stop IDs and absolute times")
                    continue
                candidates = [t for t in schedule.trips if t.route_id == descriptor.route_id
                              and t.direction_id == descriptor.direction_id and t.stop_times
                              and t.stop_times[0].departure_seconds == start]
                if len(candidates) == 1:
                    trip, = candidates
                    key = trip.trip_id
            if trip and (not trip.stop_times or trip.stop_times[0].departure_seconds != start):
                issues.append(f"{key}: trip start time mismatch")
                continue
        if (not entity.id or entity_ids[entity.id] != 1 or entity.is_deleted
                or not entity.HasField("trip_update") or trip is None):
            issues.append(f"{entity.id!r}: invalid entity or unknown trip {key!r}")
            continue
        if (descriptor.start_date and descriptor.start_date != day.strftime("%Y%m%d")
                or descriptor.route_id and descriptor.route_id != trip.route_id
                or descriptor.HasField("direction_id") and descriptor.direction_id != trip.direction_id):
            issues.append(f"{key}: service date, route or direction mismatch")
            continue
        timestamp = _optional(update, "timestamp")
        if timestamp is not None and not 0 <= as_of - timestamp <= max_age:
            issues.append(f"{key}: stale or future trip update")
            continue
        relationship = descriptor.ScheduleRelationship.Name(descriptor.schedule_relationship)
        if relationship not in ("CANCELED", "DELETED", "SCHEDULED"):
            issues.append(f"{key}: unsupported {relationship}")
            continue
        visits = _visits(update, trip, origin, issues) if relationship == "SCHEDULED" else ()
        if not descriptor.start_date:
            if not trip.stop_times:
                issues.append(f"{key}: missing static visits")
                continue
            first = trip.stop_times[0].departure_seconds
            last = trip.stop_times[-1].arrival_seconds
            if first is not None and last is not None and last - first > 86400:
                issues.append(f"{key}: multi-day trip requires start_date")
                continue
            # Compare explicit absolute predictions with the same stop times
            # on adjacent service days. A trip can be reported before it starts.
            gaps = [event.delay_seconds for visit in visits
                    for event in (visit.arrival, visit.departure)
                    if event is not None and event.delay_seconds is not None
                    and event.has_reported_time]
            if gaps:
                correct_day = (2 * min(gaps) > yesterday - origin
                               and 2 * max(gaps) < tomorrow - origin)
            else:
                # With no absolute prediction, compare the trip's operating
                # interval to the update time, including previous-day service.
                if first is None or last is None:
                    issues.append(f"{key}: missing service-day bounds")
                    continue
                moment = (timestamp or snapshot.source_timestamp) - (update.delay or 0)
                distances = [max(base + first - moment, moment - base - last, 0)
                             for base in (yesterday, origin, tomorrow)]
                correct_day = distances[1] < min(distances[0], distances[2])
            if not correct_day:
                issues.append(f"{key}: unresolved service day")
                continue
        if relationship == "SCHEDULED" and not visits:
            issues.append(f"{key}: no usable stop updates")
            continue
        if key in matched or key in duplicates:
            matched.pop(key, None)
            duplicates.add(key)
            issues.append(f"{key}: conflicting trip updates")
            continue
        matched[key] = TripUpdate(key, trip.route_id, timestamp, relationship,
                                  _optional(update, "delay"), visits)
    return matched, issues
