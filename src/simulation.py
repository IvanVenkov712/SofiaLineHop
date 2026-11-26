"""Scheduled and stochastic simulation of one transfer connection."""

from bisect import bisect_left
from dataclasses import dataclass
from math import ceil, isfinite
from operator import itemgetter
from random import Random

from .models import (
    Schedule, ScheduledEvent, SimulationParameters, StochasticTransferOutcome,
    TransferConnection, TransferOutcome, WalkingRoute,
)
from .transfers import get_transfer_events


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


def _match(arrival, actual_arrival, departures, walk, required):
    departure = _first_departure(departures, actual_arrival + required)
    if departure is None:
        return TransferOutcome(arrival.trip_id, None, False, None, None, arrival.time_seconds)
    actual_departure, event = departure
    total = actual_departure - actual_arrival
    return TransferOutcome(arrival.trip_id, event.trip_id, True, total - walk, total,
                           arrival.time_seconds, event.time_seconds)


def simulate_transfers(
    schedule: Schedule,
    connection: TransferConnection,
    walking_route: WalkingRoute,
    parameters: SimulationParameters,
    outgoing_offset_seconds: int = 0,
) -> list[TransferOutcome]:
    """Match each scheduled arrival to its first feasible in-window departure."""
    walk = walking_route.duration_seconds
    required = _required_seconds(walk, parameters.minimum_buffer_seconds)
    if parameters.arrival_delay_seconds or parameters.departure_delay_seconds or outgoing_offset_seconds:
        raise ValueError("scheduled simulation requires zero delays and schedule offset")

    events = get_transfer_events(schedule, connection, parameters.start_seconds, parameters.end_seconds)
    departures = [(event.time_seconds, event) for event in events.departures]
    return [_match(event, event.time_seconds, departures, walk, required) for event in events.arrivals]


def simulate_stochastic_transfers(
    schedule: Schedule,
    connection: TransferConnection,
    walking_route: WalkingRoute,
    parameters: SimulationParameters,
    *,
    arrival_delay: DelayModel = DelayModel(),
    departure_delay: DelayModel = DelayModel(),
    repetitions: int = 1,
    seed: int | None = None,
) -> list[list[StochasticTransferOutcome]]:
    """Return one list of scheduled arrival attempts per independent timetable draw.

    Sample each event once per repetition. SimulationParameters delays are fixed
    additions to the sampled delays. See README for cohort and horizon semantics.
    """
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError("repetitions must be a positive integer")
    for base in (parameters.arrival_delay_seconds, parameters.departure_delay_seconds):
        if type(base) is not int or base < 0:
            raise ValueError("fixed delays must be nonnegative whole seconds")

    walk = walking_route.duration_seconds
    required = _required_seconds(walk, parameters.minimum_buffer_seconds)
    events = get_transfer_events(schedule, connection, parameters.start_seconds, parameters.end_seconds)
    scheduled = [(event.time_seconds, event) for event in events.departures]
    intentions = [_first_departure(scheduled, arrival.time_seconds + required) for arrival in events.arrivals]

    rng = Random(seed)
    runs = []
    for _ in range(repetitions):
        departure_times = {
            event: event.time_seconds + parameters.departure_delay_seconds
            + rng.randint(departure_delay.minimum_seconds, departure_delay.maximum_seconds)
            for event in events.departures
        }
        departures = sorted((time, event) for event, time in departure_times.items()
                            if time < parameters.end_seconds)
        outcomes = []
        for arrival, intention in zip(events.arrivals, intentions):
            actual = (arrival.time_seconds + parameters.arrival_delay_seconds
                      + rng.randint(arrival_delay.minimum_seconds, arrival_delay.maximum_seconds))
            transfer = _match(arrival, actual, departures, walk, required)
            intended = intention[1] if intention else None
            missed = departure_times[intended] < actual + required if intended else None
            outcomes.append(StochasticTransferOutcome(transfer, actual, intended, missed))
        runs.append(outcomes)
    return runs
