"""Scheduled and stochastic simulation of one transfer connection."""

from bisect import bisect_left
from dataclasses import dataclass, replace
from math import ceil, isfinite
from operator import itemgetter
from random import Random

from .models import (
    RealtimeTransferOutcome, Schedule, ScheduledEvent, SimulationParameters, StochasticTransferOutcome,
    TransferConnection, TransferEvents, TransferOutcome, WalkingRoute,
)
from .transfers import get_transfer_events
from .realtime_schedule import RealtimeSchedule
from .gtfs_realtime import service_day_origin


@dataclass(frozen=True)
class DelayModel:
    """Discrete uniform extra delay in whole seconds, including both bounds."""

    minimum_seconds: int = 0
    maximum_seconds: int = 0

    def __post_init__(self):
        if any(type(bound) is not int for bound in (self.minimum_seconds, self.maximum_seconds)):
            raise ValueError("delay bounds must be whole seconds")
        if not 0 <= self.minimum_seconds <= self.maximum_seconds:
            raise ValueError("expected 0 <= minimum_seconds <= maximum_seconds")


def _required_seconds(walk: float, buffer: int) -> float:
    if not isfinite(walk) or walk < 0:
        raise ValueError("walking duration must be finite and nonnegative")
    if not isfinite(buffer) or buffer < 0:
        raise ValueError("minimum transfer buffer must be finite and nonnegative")
    return ceil(walk) + buffer


def _first_departure(departures: list[tuple[int, ScheduledEvent]], ready: float):
    index = bisect_left(departures, ready, key=itemgetter(0))
    return departures[index] if index < len(departures) else None


def _match(arrival, actual_arrival, departure, walk):
    if departure is None:
        return TransferOutcome(arrival.trip_id, None, False, None, None, arrival.time_seconds)
    actual_departure, event = departure
    total = actual_departure - actual_arrival
    return TransferOutcome(arrival.trip_id, event.trip_id, True, total - walk, total,
                           arrival.time_seconds, event.time_seconds)


def simulate_transfers(
    schedule: Schedule | RealtimeSchedule,
    connection: TransferConnection,
    walking_route: WalkingRoute,
    parameters: SimulationParameters,
    outgoing_offset_seconds: int = 0,
) -> list[TransferOutcome] | list[RealtimeTransferOutcome]:
    """Run a published timetable or a deterministic realtime-informed scenario."""
    if isinstance(schedule, RealtimeSchedule):
        return simulate_stochastic_transfers(schedule, connection, walking_route, parameters,
                                             outgoing_offset_seconds=outgoing_offset_seconds)[0]
    walk = walking_route.duration_seconds
    required = _required_seconds(walk, parameters.minimum_buffer_seconds)
    if parameters.arrival_delay_seconds or parameters.departure_delay_seconds or outgoing_offset_seconds:
        raise ValueError("scheduled simulation requires zero delays and schedule offset")

    events = get_transfer_events(schedule, connection, parameters.start_seconds, parameters.end_seconds)
    departures = [(event.time_seconds, event) for event in events.departures]
    return [_match(event, event.time_seconds,
                   _first_departure(departures, event.time_seconds + required), walk)
            for event in events.arrivals]


@dataclass(frozen=True)
class RealtimeEvents(TransferEvents):
    # Keys retain published times and visit identity throughout the simulation.
    arrival_conditions: dict[ScheduledEvent, tuple[int | None, str]]
    departure_conditions: dict[ScheduledEvent, tuple[int | None, str]]


def validate_realtime_window(service_date, source_timestamp, start, end):
    origin = service_day_origin(service_date)
    # A local forecast experiment starts near capture and spans at most the
    # next hour. Epoch comparison also works for archived and 24+ hour trips.
    if not (0 <= start < end and start >= source_timestamp - origin - 90
            and end <= source_timestamp - origin + 3600):
        raise ValueError("realtime window must fall within 90 s before to 1 h after the snapshot")


def _realtime_events(schedule, connection, parameters, offsets):
    start, end = parameters.start_seconds, parameters.end_seconds
    validate_realtime_window(schedule.baseline.service_date, schedule.source_timestamp, start, end)

    def conditions(leg, arriving):
        result = {}
        for trip in schedule.trips.values():
            if trip.scheduled.route_id != leg.route_id:
                continue
            if leg.direction_id is not None and trip.scheduled.direction_id != leg.direction_id:
                continue
            for visit in trip.visits:
                call = visit.scheduled
                if call.stop_id != leg.stop_id or not (call.can_alight if arriving else call.can_board):
                    continue
                timing = visit.arrival if arriving else visit.departure
                published = timing.scheduled_seconds
                if published is None:
                    continue
                effective = timing.effective_seconds
                if arriving:
                    eligible = start <= published < end
                else:
                    eligible = any(start <= t + shift < end for t in (published, effective)
                                   if t is not None for shift in offsets)
                if eligible:
                    key = ScheduledEvent(published, trip.scheduled.trip_id, call.stop_sequence)
                    source = visit.relationship if timing.source == "suppressed" else timing.source
                    result[key] = effective, source
        return result

    arrivals = conditions(connection.incoming, True)
    departures = conditions(connection.outgoing, False)
    return RealtimeEvents(tuple(sorted(arrivals)), tuple(sorted(departures)), arrivals, departures)


def offset_event_pool(schedule, connection, parameters, offsets) -> TransferEvents:
    """Keep the arrival cohort fixed and include departures that can shift into view."""
    if isinstance(schedule, RealtimeSchedule):
        return _realtime_events(schedule, connection, parameters, offsets)
    start, end = parameters.start_seconds, parameters.end_seconds
    baseline = get_transfer_events(schedule, connection, start, end)
    pool_start = max(0, start - max(offsets))
    pool_end = end - min(offsets)
    if (pool_start, pool_end) == (start, end):
        return baseline
    pool = get_transfer_events(schedule, connection, pool_start, pool_end)
    return TransferEvents(baseline.arrivals, pool.departures)


def simulate_stochastic_transfers(
    schedule: Schedule | RealtimeSchedule,
    connection: TransferConnection,
    walking_route: WalkingRoute,
    parameters: SimulationParameters,
    *,
    arrival_delay: DelayModel = DelayModel(),
    departure_delay: DelayModel = DelayModel(),
    repetitions: int = 1,
    seed: int | None = None,
    outgoing_offset_seconds: int = 0,
) -> list[list[StochasticTransferOutcome]] | list[list[RealtimeTransferOutcome]]:
    """Return one list of scheduled arrival attempts per independent timetable draw.

    Sample each event once per repetition. SimulationParameters delays are fixed
    additions to the sampled delays. See README for cohort and horizon semantics.
    """
    events = offset_event_pool(schedule, connection, parameters, (0, outgoing_offset_seconds))
    return list(simulate_event_runs(events, walking_route, parameters, arrival_delay,
                                    departure_delay, repetitions, seed, outgoing_offset_seconds))


def simulate_event_runs(
    events: TransferEvents, walking_route: WalkingRoute, parameters: SimulationParameters,
    arrival_delay: DelayModel, departure_delay: DelayModel, repetitions: int,
    seed: int | None, outgoing_offset_seconds: int = 0,
):
    """Simulate a fixed arrival cohort and a common pool of candidate departures.

    Draw delays for the whole pool so moving a visit across a window boundary
    preserves every other visit's draw when replaying the seed.
    """
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError("repetitions must be a positive integer")
    for base in (parameters.arrival_delay_seconds, parameters.departure_delay_seconds):
        if type(base) is not int or base < 0:
            raise ValueError("fixed delays must be nonnegative whole seconds")

    walk = walking_route.duration_seconds
    required = _required_seconds(walk, parameters.minimum_buffer_seconds)
    realtime = isinstance(events, RealtimeEvents)
    start, end = parameters.start_seconds, parameters.end_seconds
    shifted = {
        event: replace(event, time_seconds=event.time_seconds + outgoing_offset_seconds)
        for event in events.departures
    }
    scheduled = [(event.time_seconds, event) for event in shifted.values() if start <= event.time_seconds < end]
    intentions = [_first_departure(scheduled, arrival.time_seconds + required) for arrival in events.arrivals]
    published_visits = {shifted[event]: event for event in events.departures} if realtime else {}

    rng = Random(seed)
    for _ in range(repetitions):
        departure_times = {}
        departures = []
        for event in events.departures:
            delay = rng.randint(departure_delay.minimum_seconds, departure_delay.maximum_seconds)
            base = events.departure_conditions[event][0] if realtime else event.time_seconds
            if base is None:
                continue
            visit = shifted[event]
            shifted_base = base + outgoing_offset_seconds
            modeled = shifted_base + parameters.departure_delay_seconds + delay
            departure_times[visit] = modeled
            if start <= shifted_base < end and modeled < end:
                departures.append((modeled, visit))
        departures.sort()
        outcomes = []
        for arrival, intention in zip(events.arrivals, intentions):
            base, source = events.arrival_conditions[arrival] if realtime else (arrival.time_seconds, "scheduled")
            extra = parameters.arrival_delay_seconds + rng.randint(arrival_delay.minimum_seconds, arrival_delay.maximum_seconds)
            modeled = base + extra if base is not None else None
            boarded = _first_departure(departures, modeled + required) if modeled is not None else None
            transfer = _match(arrival, modeled, boarded, walk)
            intended = intention[1] if intention else None
            missed = None
            if intended and modeled is not None:
                missed = intended not in departure_times or departure_times[intended] < modeled + required
            if realtime:
                published_boarding = published_visits[boarded[1]] if boarded else None
                published_intention = published_visits[intended] if intended else None
                outcomes.append(RealtimeTransferOutcome(
                    transfer, arrival, modeled, boarded[0] if boarded else None, source,
                    events.departure_conditions[published_boarding][1] if boarded else None,
                    published_intention, missed,
                    events.departure_conditions[published_intention][1] if intended else None,
                    published_boarding,
                ))
            else:
                outcomes.append(StochasticTransferOutcome(transfer, modeled, intended, missed))
        yield outcomes
