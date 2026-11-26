"""Service-day view combining a static timetable and one full Trip Updates snapshot."""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

from .gtfs_realtime import Prediction, Snapshot, TripUpdate, match_updates, service_day_origin
from .models import Schedule, StopTime, Trip


@dataclass(frozen=True, slots=True)
class EventTime:
    """Times in service-day seconds. A fallback always has unknown delay."""

    scheduled_seconds: int | None
    updated_seconds: int | None
    delay_seconds: int | None
    source: str

    @property
    def effective_seconds(self):
        if self.source == "scheduled_fallback":
            return self.scheduled_seconds
        return self.updated_seconds


@dataclass(frozen=True, slots=True)
class RealtimeVisit:
    scheduled: StopTime
    relationship: str
    arrival: EventTime
    departure: EventTime

    @property
    def can_board(self):
        return self.scheduled.can_board and self.relationship not in ("CANCELED", "DELETED", "SKIPPED")

    @property
    def can_alight(self):
        return self.scheduled.can_alight and self.relationship not in ("CANCELED", "DELETED", "SKIPPED")


@dataclass(frozen=True, slots=True)
class RealtimeTrip:
    scheduled: Trip
    update: TripUpdate | None
    visits: tuple[RealtimeVisit, ...]


@dataclass(frozen=True)
class Coverage:
    total_trips: int
    matched_trips: int
    total_events: int
    reported_events: int
    propagated_events: int
    fallback_events: int
    unavailable_events: int
    suppressed_events: int

    @property
    def trip_fraction(self):
        return self.matched_trips / self.total_trips if self.total_trips else None

    @property
    def timing_fraction(self):
        """Fraction of arrival/departure slots with an explicit or inferred prediction."""
        predicted = self.reported_events + self.propagated_events
        return predicted / self.total_events if self.total_events else None


@dataclass(frozen=True)
class RealtimeSchedule:
    baseline: Schedule
    source_timestamp: int
    retrieved_at: int
    trips: Mapping[str, RealtimeTrip]
    issues: tuple[str, ...]

    def coverage(self, route_id: str | None = None) -> Coverage:
        counts = Counter()
        total = matched = 0
        for trip in self.trips.values():
            if route_id is not None and trip.scheduled.route_id != route_id:
                continue
            total += 1
            matched += trip.update is not None
            for visit in trip.visits:
                counts[visit.arrival.source] += 1
                counts[visit.departure.source] += 1
        return Coverage(total, matched, counts.total(), counts["reported"],
                        counts["propagated"] + counts["trip_delay"], counts["scheduled_fallback"],
                        counts["unavailable"], counts["suppressed"])


def _event(scheduled, prediction: Prediction | None, origin, delay, source):
    if prediction is not None:
        return EventTime(scheduled, prediction.timestamp - origin, prediction.delay_seconds, "reported")
    if source == "suppressed":
        return EventTime(scheduled, None, None, source)
    if scheduled is None:
        return EventTime(None, None, None, "unavailable")
    if delay is None:
        return EventTime(scheduled, None, None, "scheduled_fallback")
    return EventTime(scheduled, scheduled + delay, delay, source)


def _integrate_trip(trip, update, origin):
    explicit = {v.stop_sequence: v for v in update.visits} if update else {}
    delay = update.delay_seconds if update else None
    source = "trip_delay"
    visits = []
    canceled = update is not None and update.relationship in ("CANCELED", "DELETED")
    no_data = False
    for call in trip.stop_times:
        visit = explicit.get(call.stop_sequence)
        if visit and visit.relationship != "SKIPPED":
            no_data = visit.relationship == "NO_DATA"
        relationship = "NO_DATA" if no_data else "SCHEDULED"
        if canceled:
            relationship = update.relationship
        elif visit:
            relationship = visit.relationship

        if canceled or relationship == "SKIPPED":
            arrival = _event(call.arrival_seconds, None, origin, None, "suppressed")
            departure = _event(call.departure_seconds, None, origin, None, "suppressed")
        else:
            if visit:
                # A new stop update ends upstream propagation. An arrival can
                # carry its delay forward to departure, never the reverse.
                delay = None
                source = "propagated"
            arrival = _event(call.arrival_seconds, visit.arrival if visit else None, origin, delay, source)
            if visit and visit.arrival:
                delay = arrival.delay_seconds
            departure = _event(call.departure_seconds, visit.departure if visit else None, origin, delay, source)
            if visit and visit.departure:
                delay = departure.delay_seconds
        visits.append(RealtimeVisit(call, relationship, arrival, departure))
    return RealtimeTrip(trip, update, tuple(visits))


def integrate_schedule(schedule: Schedule, snapshot: Snapshot, *, as_of: int | None = None,
                       max_age: int = 90) -> RealtimeSchedule:
    """Overlay a snapshot on a full, unfiltered static service-day schedule."""
    updates, issues = match_updates(snapshot, schedule, as_of=as_of, max_age=max_age)
    origin = service_day_origin(schedule.service_date)
    trips = {t.trip_id: _integrate_trip(t, updates.get(t.trip_id), origin) for t in schedule.trips}
    # Trip and stop-time records are frozen. Isolate the two mutable static indexes.
    baseline = replace(schedule, stops=MappingProxyType(dict(schedule.stops)),
                       routes=MappingProxyType(dict(schedule.routes)))
    return RealtimeSchedule(baseline, snapshot.source_timestamp, snapshot.retrieved_at,
                            MappingProxyType(trips), tuple(issues))
