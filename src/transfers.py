"""Discover walking connections and query their service-day timetables."""

from collections import defaultdict
from math import isfinite

import networkx as nx

from .models import Schedule, ScheduledEvent, TransferConnection, TransferEvents, TransferLeg
from .pedestrian_network import associate_stops


def _selected_trips(schedule: Schedule, route_id: str, direction_id: int | None):
    return (
        trip for trip in schedule.trips
        if trip.route_id == route_id and (direction_id is None or trip.direction_id == direction_id)
    )


def find_transfers(
    schedule: Schedule, max_stop_distance_meters: float, *, network: nx.MultiDiGraph,
    incoming_route_id: str, outgoing_route_id: str,
    incoming_direction_id: int | None = None, outgoing_direction_id: int | None = None,
    max_snap_distance_m: float | None = None,
) -> list[TransferConnection]:
    """Find ordered stop pairs on distinct routes active on schedule.service_date.

    A missing direction selects all directions of that route. The inclusive limit
    applies to directed walking distance between snapped nodes, excluding the snap
    distances, as in find_walking_route. Untimed calls can identify locations.
    """
    if not isfinite(max_stop_distance_meters) or max_stop_distance_meters < 0:
        raise ValueError("max_stop_distance_meters must be finite and nonnegative")
    if incoming_route_id == outgoing_route_id:
        return []

    origins = {call.stop_id
               for trip in _selected_trips(schedule, incoming_route_id, incoming_direction_id)
               for call in trip.stop_times if call.can_alight}
    destinations = {call.stop_id
                    for trip in _selected_trips(schedule, outgoing_route_id, outgoing_direction_id)
                    for call in trip.stop_times if call.can_board}
    if not origins or not destinations:
        return []
    stop_ids = sorted(origins | destinations)
    nodes = associate_stops(network, [schedule.stops[s] for s in stop_ids],
                            max_snap_distance_m=max_snap_distance_m)
    origin_nodes = defaultdict(list)
    destination_nodes = defaultdict(list)
    for stop_id, node in zip(stop_ids, nodes):
        if node is None:
            continue
        if stop_id in origins:
            origin_nodes[node].append(TransferLeg(incoming_route_id, stop_id, incoming_direction_id))
        if stop_id in destinations:
            destination_nodes[node].append(TransferLeg(outgoing_route_id, stop_id, outgoing_direction_id))

    connections = []
    for node, incoming_legs in origin_nodes.items():
        reachable = nx.single_source_dijkstra_path_length(
            network, node, cutoff=max_stop_distance_meters, weight="length"
        )
        for target in reachable.keys() & destination_nodes.keys():
            connections.extend(TransferConnection(origin, destination)
                               for origin in incoming_legs for destination in destination_nodes[target])
    return sorted(connections, key=lambda c: (c.incoming.stop_id, c.outgoing.stop_id))


def get_transfer_events(
    schedule: Schedule, connection: TransferConnection, start_seconds: int, end_seconds: int,
) -> TransferEvents:
    """Return scheduled events in [start_seconds, end_seconds) on schedule.service_date.

    Bounds may extend past midnight. Each timed visit to a transfer stop is
    returned independently, including repeated visits by a single trip.
    """
    if start_seconds < 0 or end_seconds <= start_seconds:
        raise ValueError("expected a nonnegative start and an end greater than the start")

    def events(leg: TransferLeg, *, arriving: bool) -> tuple[ScheduledEvent, ...]:
        selected = []
        for trip in _selected_trips(schedule, leg.route_id, leg.direction_id):
            for call in trip.stop_times:
                if call.stop_id != leg.stop_id:
                    continue
                if arriving and call.can_alight:
                    time = call.arrival_seconds
                elif not arriving and call.can_board:
                    time = call.departure_seconds
                else:
                    continue
                if time is not None and start_seconds <= time < end_seconds:
                    selected.append(ScheduledEvent(time, trip.trip_id, call.stop_sequence))
        return tuple(sorted(selected))

    return TransferEvents(events(connection.incoming, arriving=True),
                          events(connection.outgoing, arriving=False))
