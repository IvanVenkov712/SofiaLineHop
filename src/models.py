"""Shared records. Schedule times are seconds from the GTFS service-day origin
and may exceed 24 hours. Identifiers retain their original GTFS strings.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Stop:
    stop_id: str
    name: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Route:
    route_id: str
    short_name: str
    long_name: str


@dataclass(frozen=True)
class StopTime:
    stop_id: str
    stop_sequence: int
    arrival_seconds: int | None
    departure_seconds: int | None
    can_alight: bool = True
    can_board: bool = True


@dataclass(frozen=True)
class Trip:
    """One active trip with stop times ordered by stop_sequence."""

    trip_id: str
    route_id: str
    direction_id: int | None
    stop_times: tuple[StopTime, ...]


@dataclass(frozen=True)
class Schedule:
    """Stops and routes keyed by ID, and trips active on service_date."""

    service_date: date
    stops: dict[str, Stop]
    routes: dict[str, Route]
    trips: tuple[Trip, ...]


@dataclass(frozen=True)
class TransferLeg:
    """A route serving a transfer stop, optionally restricted by direction."""

    route_id: str
    stop_id: str
    direction_id: int | None = None


@dataclass(frozen=True)
class TransferConnection:
    incoming: TransferLeg
    outgoing: TransferLeg


@dataclass(frozen=True, order=True)
class ScheduledEvent:
    """A scheduled arrival or departure, ordered by time on the service day."""

    time_seconds: int
    trip_id: str
    stop_sequence: int


@dataclass(frozen=True)
class TransferEvents:
    arrivals: tuple[ScheduledEvent, ...]
    departures: tuple[ScheduledEvent, ...]


@dataclass(frozen=True)
class WalkingRoute:
    """Walking cost between snapped nodes and WGS84 (longitude, latitude) vertices."""

    node_ids: tuple[int, ...]
    distance_meters: float
    duration_seconds: float
    geometry: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class SimulationParameters:
    """Select scheduled incoming arrivals in [start_seconds, end_seconds)."""

    start_seconds: int
    end_seconds: int
    minimum_buffer_seconds: int = 0
    arrival_delay_seconds: int = 0
    departure_delay_seconds: int = 0


@dataclass(frozen=True)
class TransferOutcome:
    """One attempted transfer. Elapsed times are absent for a missed transfer.

    Waiting starts when walking ends. Total duration starts at actual arrival.
    Both end at actual departure.
    """

    incoming_trip_id: str
    outgoing_trip_id: str | None
    successful: bool
    waiting_seconds: float | None
    total_duration_seconds: float | None


@dataclass(frozen=True)
class TransferMetrics:
    """Time statistics cover successes. Rates are fractions of all attempts.

    A statistic is None when its sample is empty.
    """

    mean_waiting_seconds: float | None
    median_waiting_seconds: float | None
    maximum_waiting_seconds: float | None
    mean_total_duration_seconds: float | None
    successful_rate: float | None
    missed_rate: float | None
