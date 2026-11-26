"""Compare local outgoing schedule changes for one transfer connection."""

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import chain
from secrets import randbits

from .analytics import summarize_transfers
from .models import (
    Schedule, SimulationParameters, TransferConnection, TransferEvents, TransferMetrics, WalkingRoute,
)
from .simulation import DelayModel, simulate_event_runs
from .transfers import get_transfer_events


@dataclass(frozen=True)
class OptimizationResult:
    scenarios: dict[int, TransferMetrics]
    best_offset_seconds: int


def evaluate_offsets(
    schedule: Schedule,
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

    start, end = parameters.start_seconds, parameters.end_seconds
    baseline = get_transfer_events(schedule, connection, start, end)
    # A visit outside the original window can become available after shifting.
    pool_start = max(0, start - max(offsets))
    pool_end = end - min(offsets)
    pool = (baseline if (pool_start, pool_end) == (start, end)
            else get_transfer_events(schedule, connection, pool_start, pool_end))
    events = TransferEvents(baseline.arrivals, pool.departures)
    common_seed = randbits(128) if seed is None else seed
    scenarios = {}
    for offset in sorted(offsets):
        runs = simulate_event_runs(events, walking_route, parameters, arrival_delay,
                                   departure_delay, repetitions, common_seed, offset)
        scenarios[offset] = summarize_transfers(chain.from_iterable(runs))
    return scenarios


def optimize_offsets(
    schedule: Schedule, connection: TransferConnection, walking_route: WalkingRoute,
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

    offsets = range(min_offset_seconds, max_offset_seconds + 1, step_seconds)
    scenarios = evaluate_offsets(schedule, connection, walking_route, parameters, offsets,
                                 arrival_delay=arrival_delay, departure_delay=departure_delay,
                                 repetitions=repetitions, seed=seed)
    baseline_rate = scenarios[0].successful_rate
    candidates = []
    for offset, metrics in scenarios.items():
        value = getattr(metrics, criterion)
        if value is None or baseline_rate is None or metrics.successful_rate < baseline_rate:
            continue
        score = -value if criterion == "successful_rate" else value
        candidates.append((score, abs(offset), offset))
    best = min(candidates)[2] if candidates else 0
    return OptimizationResult(scenarios, best)
