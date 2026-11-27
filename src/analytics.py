"""Summary statistics for scheduled and stochastic transfer attempts."""

from collections import defaultdict
from collections.abc import Iterable
from math import isfinite
from statistics import fmean, median, pstdev

import numpy as np

from .models import RealtimeTransferOutcome, StochasticTransferOutcome, TransferMetrics, TransferOutcome

Outcome = TransferOutcome | StochasticTransferOutcome | RealtimeTransferOutcome
DEFAULT_PERCENTILES = (50, 90, 95)


def _percentile_levels(percentiles: Iterable[float]) -> tuple[float, ...]:
    levels = tuple(percentiles)
    if any(not isfinite(level) or not 0 <= level <= 100 for level in levels):
        raise ValueError("percentiles must be finite values from 0 to 100")
    return levels


def summarize_transfers(
    outcomes: Iterable[Outcome], *, percentiles: Iterable[float] = DEFAULT_PERCENTILES
) -> TransferMetrics:
    """Summarize one observation per attempt. Undefined statistics are None.

    Mean, median, maximum, population standard deviation and linear percentiles
    use completed waits in seconds. Mean duration uses the same completions.
    Completion and incompletion rates divide by all attempts. The intended
    connection miss rate divides by attempts with a modeled arrival and an intended departure.
    """
    levels = _percentile_levels(percentiles)
    waits: list[float] = []
    durations: list[float] = []
    attempts = intended = misses = 0
    for outcome in outcomes:
        attempts += 1
        if isinstance(outcome, (StochasticTransferOutcome, RealtimeTransferOutcome)):
            transfer = outcome.transfer
            if outcome.missed_intended_connection is not None:
                intended += 1
                misses += outcome.missed_intended_connection
        else:
            transfer = outcome
            # In the scheduled simulation every feasible intention is boarded.
            intended += transfer.successful

        if transfer.successful:
            if transfer.waiting_seconds is None or transfer.total_duration_seconds is None:
                raise ValueError("completed transfers require waiting time and total duration")
            waits.append(transfer.waiting_seconds)
            durations.append(transfer.total_duration_seconds)

    quantiles = (dict(zip(levels, map(float, np.percentile(waits, levels))))
                 if waits and levels else dict.fromkeys(levels))
    return TransferMetrics(
        mean_waiting_seconds=fmean(waits) if waits else None,
        median_waiting_seconds=median(waits) if waits else None,
        maximum_waiting_seconds=max(waits, default=None),
        mean_total_duration_seconds=fmean(durations) if durations else None,
        successful_rate=len(waits) / attempts if attempts else None,
        missed_rate=(attempts - len(waits)) / attempts if attempts else None,
        waiting_std_seconds=pstdev(waits) if waits else None,
        waiting_percentiles_seconds=quantiles,
        missed_connection_rate=misses / intended if intended else None,
    )


def summarize_transfers_by_interval(
    outcomes: Iterable[Outcome], interval_seconds: int, *,
    percentiles: Iterable[float] = DEFAULT_PERCENTILES,
) -> dict[int, TransferMetrics]:
    """Return occupied intervals keyed by start, ordered by scheduled arrival.

    Intervals are half-open and aligned to second zero of the GTFS service day.
    An attempt without a scheduled arrival cannot be grouped.
    """
    if type(interval_seconds) is not int or interval_seconds <= 0:
        raise ValueError("interval_seconds must be a positive whole number")
    levels = _percentile_levels(percentiles)
    groups: dict[int, list[Outcome]] = defaultdict(list)
    for outcome in outcomes:
        transfer = outcome if isinstance(outcome, TransferOutcome) else outcome.transfer
        arrival = transfer.scheduled_arrival_seconds
        if arrival is None:
            raise ValueError("interval aggregation requires a scheduled arrival time")
        groups[arrival - arrival % interval_seconds].append(outcome)

    return {start: summarize_transfers(groups[start], percentiles=levels) for start in sorted(groups)}
