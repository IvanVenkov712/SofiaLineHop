"""Compare local outgoing schedule changes for one transfer connection."""

from collections.abc import Iterable
from collections import Counter
from dataclasses import dataclass
from datetime import date
from itertools import chain
from secrets import randbits

from .analytics import summarize_transfers
from .models import (
    Schedule, SimulationParameters, TransferConnection, TransferEvents, TransferMetrics, WalkingRoute,
)
from .realtime_schedule import RealtimeSchedule
from .simulation import DelayModel, RealtimeEvents, offset_event_pool, simulate_event_runs


@dataclass(frozen=True)
class ConnectionRecommendation:
    connection: TransferConnection
    service_date: date
    start_seconds: int
    end_seconds: int
    offset_seconds: int
    action: str
    criterion: str
    baseline: TransferMetrics
    proposed: TransferMetrics
    snapshot_timestamp: int


@dataclass(frozen=True)
class OptimizationResult:
    scenarios: dict[int, TransferMetrics]
    best_offset_seconds: int
    published_reference: TransferMetrics | None = None
    recommendation: ConnectionRecommendation | None = None
    arrival_sources: dict[str, int] | None = None
    departure_sources: dict[str, int] | None = None


def evaluate_offsets(
    schedule: Schedule | RealtimeSchedule,
    connection: TransferConnection,
    walking_route: WalkingRoute,
    parameters: SimulationParameters,
    outgoing_offsets_seconds: Iterable[int],
    *,
    arrival_delay: DelayModel = DelayModel(),
    departure_delay: DelayModel = DelayModel(),
    repetitions: int = 1,
    seed: int | None = None,
) -> dict[int, TransferMetrics]:
    """Return pooled metrics for every distinct offset and the original timetable."""
    offsets = {0}
    for offset in outgoing_offsets_seconds:
        if type(offset) is not int:
            raise ValueError("offsets must be whole seconds")
        offsets.add(offset)

    events = offset_event_pool(schedule, connection, parameters, offsets)
    common_seed = randbits(128) if seed is None else seed
    return _evaluate(events, offsets, walking_route, parameters, arrival_delay, departure_delay,
                     repetitions, common_seed)


def _evaluate(events, offsets, walking_route, parameters, arrival_delay, departure_delay,
              repetitions, common_seed):
    scenarios = {}
    for offset in sorted(offsets):
        runs = simulate_event_runs(events, walking_route, parameters, arrival_delay,
                                   departure_delay, repetitions, common_seed, offset)
        scenarios[offset] = summarize_transfers(chain.from_iterable(runs))
    return scenarios


def optimize_offsets(
    schedule: Schedule | RealtimeSchedule, connection: TransferConnection, walking_route: WalkingRoute,
    parameters: SimulationParameters, *, min_offset_seconds: int, max_offset_seconds: int,
    step_seconds: int = 1, criterion: str = "mean_waiting_seconds",
    arrival_delay: DelayModel = DelayModel(), departure_delay: DelayModel = DelayModel(),
    repetitions: int = 1, seed: int | None = None,
) -> OptimizationResult:
    """Search an inclusive integer grid and return all metrics, keyed by offset.

    Only scenarios completing at least as many attempts as baseline can win.
    Ties favor the smallest absolute change, then the earlier departure.
    """
    if any(type(i) is not int for i in (min_offset_seconds, max_offset_seconds, step_seconds)):
        raise ValueError("offset bounds and step must be whole seconds")
    if min_offset_seconds > max_offset_seconds or step_seconds <= 0:
        raise ValueError("expected ordered offset bounds and a positive step")
    if criterion not in ("mean_waiting_seconds", "median_waiting_seconds",
                         "maximum_waiting_seconds", "mean_total_duration_seconds",
                         "successful_rate", "incomplete_rate"):
        raise ValueError(f"unsupported optimization criterion: {criterion}")

    offsets = set(range(min_offset_seconds, max_offset_seconds + 1, step_seconds)) | {0}
    events = offset_event_pool(schedule, connection, parameters, offsets)
    common_seed = randbits(128) if seed is None else seed
    options = walking_route, parameters, arrival_delay, departure_delay, repetitions, common_seed
    scenarios = _evaluate(events, offsets, *options)
    baseline_rate = scenarios[0].successful_rate
    candidates = []
    for offset, metrics in scenarios.items():
        value = getattr(metrics, criterion)
        if value is None or baseline_rate is None or metrics.successful_rate < baseline_rate:
            continue
        score = -value if criterion == "successful_rate" else value
        candidates.append((score, abs(offset), offset))
    best = min(candidates)[2] if candidates else 0
    if isinstance(events, RealtimeEvents):
        # Same incoming cohort, ordered departure pool and draws in both references.
        published = _evaluate(TransferEvents(events.arrivals, events.departures), [0], *options)[0]
        arrivals = Counter(source for _, source in events.arrival_conditions.values())
        departures = Counter()
        for event, (modeled, source) in events.departure_conditions.items():
            if any(parameters.start_seconds <= time + shift < parameters.end_seconds
                   for time in (event.time_seconds, modeled) if time is not None for shift in (0, best)):
                departures[source] += 1
        recommendation = None
        if candidates and (arrivals.keys() | departures.keys()) - {"scheduled_fallback", "unavailable"}:
            action = "Retain the current departure time"
            if best:
                direction = "later" if best > 0 else "earlier"
                action = f"Shift departures {abs(best)} seconds {direction}"
            leg = connection.outgoing
            recommendation = ConnectionRecommendation(
                connection, schedule.baseline.service_date, parameters.start_seconds, parameters.end_seconds,
                best, f"{action} on {leg.route_id} at {leg.stop_id}",
                criterion, scenarios[0], scenarios[best], schedule.source_timestamp)
        return OptimizationResult(scenarios, best, published, recommendation, dict(arrivals), dict(departures))
    return OptimizationResult(scenarios, best)
