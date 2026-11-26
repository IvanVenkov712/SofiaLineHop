import pytest

from src.analytics import summarize_transfers, summarize_transfers_by_interval
from src.models import ScheduledEvent, StochasticTransferOutcome, TransferOutcome


def transfer(arrival, wait=None):
    if wait is None:
        return TransferOutcome("in", None, False, None, None, arrival)
    return TransferOutcome("in", "out", True, wait, wait + 4, arrival)


def stochastic(arrival, wait, missed):
    intended = ScheduledEvent(arrival + 4, "original", 1) if missed is not None else None
    return StochasticTransferOutcome(transfer(arrival, wait), arrival + 60, intended, missed)


def test_metrics_separate_misses_from_incompletes():
    outcomes = [
        stochastic(0, 0, False),
        stochastic(10, 10, True),   # Caught a later departure.
        stochastic(20, None, False),  # Intended departure delayed beyond horizon.
        stochastic(30, None, None),
    ]
    metrics = summarize_transfers(iter(outcomes), percentiles=(0, 25, 95, 100))
    assert metrics.mean_waiting_seconds == metrics.median_waiting_seconds == 5
    assert metrics.maximum_waiting_seconds == 10
    assert metrics.waiting_std_seconds == 5
    assert metrics.waiting_percentiles_seconds == {0: 0, 25: 2.5, 95: 9.5, 100: 10}
    assert metrics.mean_total_duration_seconds == 9
    assert metrics.missed_connection_rate == pytest.approx(1 / 3)
    assert metrics.incomplete_rate == metrics.missed_rate == metrics.successful_rate == 0.5


@pytest.mark.parametrize("outcomes, incomplete, success", [
    ([], None, None), ([transfer(0)], 1, 0),
])
def test_undefined_metrics(outcomes, incomplete, success):
    metrics = summarize_transfers(outcomes)
    assert metrics.mean_waiting_seconds is metrics.median_waiting_seconds is None
    assert metrics.maximum_waiting_seconds is metrics.waiting_std_seconds is None
    assert metrics.mean_total_duration_seconds is metrics.missed_connection_rate is None
    assert metrics.waiting_percentiles_seconds == {50: None, 90: None, 95: None}
    assert metrics.incomplete_rate == incomplete
    assert metrics.successful_rate == success


def test_interval_boundaries_use_scheduled_service_day_seconds():
    groups = summarize_transfers_by_interval(
        [transfer(86400, 8), stochastic(86399, 2, True), transfer(86401)],
        60, percentiles=iter([75]),
    )
    assert list(groups) == [86340, 86400]
    assert groups[86340].missed_connection_rate == 1
    assert groups[86340].waiting_percentiles_seconds == {75: 2}
    assert groups[86400].waiting_percentiles_seconds == {75: 8}
    assert groups[86400].incomplete_rate == 0.5
    assert groups[86400].missed_connection_rate == groups[86400].waiting_std_seconds == 0
    assert summarize_transfers_by_interval([], 60) == {}


@pytest.mark.parametrize("interval", [0, -1, 2.5])
def test_invalid_interval(interval):
    with pytest.raises(ValueError, match="interval_seconds"):
        summarize_transfers_by_interval([], interval)


def test_missing_arrival_only_prevents_grouping():
    outcome = transfer(None, 1)
    assert summarize_transfers([outcome]).mean_waiting_seconds == 1
    with pytest.raises(ValueError, match="scheduled arrival"):
        summarize_transfers_by_interval([outcome], 60)


@pytest.mark.parametrize("level", [-1, 101, float("nan")])
def test_invalid_percentile(level):
    with pytest.raises(ValueError, match="percentiles"):
        summarize_transfers([], percentiles=[level])
