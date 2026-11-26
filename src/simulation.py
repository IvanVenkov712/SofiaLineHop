"""Deterministic simulation of one scheduled transfer connection."""

from bisect import bisect_left
from math import ceil, isfinite
from operator import attrgetter

from .models import Schedule, SimulationParameters, TransferConnection, TransferOutcome, WalkingRoute
from .transfers import get_transfer_events


def simulate_transfers(
    schedule: Schedule,
    connection: TransferConnection,
    walking_route: WalkingRoute,
    parameters: SimulationParameters,
    outgoing_offset_seconds: int = 0,
) -> list[TransferOutcome]:
    """Match each arrival to the first departure allowing the walk and buffer.

    Both events must fall in [start_seconds, end_seconds). Each arrival is
    evaluated independently. Waiting includes the buffer spent at the stop.
    """
    walk = walking_route.duration_seconds
    buffer = parameters.minimum_buffer_seconds
    if not isfinite(walk) or walk < 0:
        raise ValueError("walking duration must be finite and nonnegative")
    if not isfinite(buffer) or buffer < 0:
        raise ValueError("minimum transfer buffer must be finite and nonnegative")
    if parameters.arrival_delay_seconds or parameters.departure_delay_seconds or outgoing_offset_seconds:
        raise ValueError("scheduled simulation requires zero delays and schedule offset")

    events = get_transfer_events(schedule, connection, parameters.start_seconds, parameters.end_seconds)
    # GTFS events occur on whole seconds. Round the walk up only for matching.
    required_seconds = ceil(walk) + buffer
    outcomes = []
    for arrival in events.arrivals:
        ready = arrival.time_seconds + required_seconds
        index = bisect_left(events.departures, ready, key=attrgetter("time_seconds"))
        if index == len(events.departures):
            outcomes.append(TransferOutcome(
                incoming_trip_id=arrival.trip_id, outgoing_trip_id=None, successful=False,
                waiting_seconds=None, total_duration_seconds=None,
                scheduled_arrival_seconds=arrival.time_seconds,
            ))
            continue

        departure = events.departures[index]
        total = departure.time_seconds - arrival.time_seconds
        outcomes.append(TransferOutcome(
            incoming_trip_id=arrival.trip_id, outgoing_trip_id=departure.trip_id, successful=True,
            waiting_seconds=total - walk, total_duration_seconds=total,
            scheduled_arrival_seconds=arrival.time_seconds, scheduled_departure_seconds=departure.time_seconds,
        ))
    return outcomes
