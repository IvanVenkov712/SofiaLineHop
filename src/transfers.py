"""Public interface for discovering candidate connections."""

from .models import Schedule, TransferConnection


def find_transfers(
    schedule: Schedule, max_stop_distance_meters: float
) -> list[TransferConnection]:
    """Find connections between distinct routes within the straight-line distance limit."""
    raise NotImplementedError
