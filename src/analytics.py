"""Public interface for summarizing transfer outcomes."""

from collections.abc import Iterable

from .models import TransferMetrics, TransferOutcome


def summarize_transfers(outcomes: Iterable[TransferOutcome]) -> TransferMetrics:
    """Aggregate waiting times, transfer durations and success and miss rates."""
    raise NotImplementedError
