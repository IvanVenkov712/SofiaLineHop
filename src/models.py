"""Shared records. Schedule times are seconds from the GTFS service-day origin
and may exceed 24 hours. Identifiers retain their original GTFS strings.
"""

from dataclasses import dataclass, field
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


@dataclass(frozen=True, slots=True)
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
    feed_version: str | None = None


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
    scheduled_arrival_seconds: int | None = None
    scheduled_departure_seconds: int | None = None


@dataclass(frozen=True)
class TransferMetrics:
    """Times cover completed transfers. See src.analytics for rate denominators."""

    mean_waiting_seconds: float | None
    median_waiting_seconds: float | None
    maximum_waiting_seconds: float | None
    mean_total_duration_seconds: float | None
    successful_rate: float | None
    missed_rate: float | None
    waiting_std_seconds: float | None = None
    waiting_percentiles_seconds: dict[float, float | None] = field(default_factory=dict)
    missed_connection_rate: float | None = None

    @property
    def incomplete_rate(self) -> float | None:
        """Fraction of attempts without a boarding, historically called missed_rate."""
        return self.missed_rate


@dataclass(frozen=True)
class StochasticTransferOutcome:
    """Realized transfer and feasibility of the originally intended stop visit."""

    transfer: TransferOutcome
    actual_arrival_seconds: int
    intended_departure: ScheduledEvent | None
    missed_intended_connection: bool | None


@dataclass(frozen=True)
class RealtimeTransferOutcome:
    """One published incoming visit evaluated using a forecast snapshot."""

    transfer: TransferOutcome
    incoming_visit: ScheduledEvent
    modeled_arrival_seconds: int | None
    modeled_departure_seconds: int | None
    arrival_source: str
    departure_source: str | None
    intended_departure: ScheduledEvent | None
    missed_intended_connection: bool | None
    intended_departure_source: str | None
    boarded_visit: ScheduledEvent | None
