"""Public interface for comparing schedule offsets at a selected connection."""

from collections.abc import Iterable

from .models import Schedule, SimulationParameters, TransferConnection, TransferMetrics, WalkingRoute


def evaluate_offsets(
    schedule: Schedule,
    connection: TransferConnection,
    walking_route: WalkingRoute,
    parameters: SimulationParameters,
    outgoing_offsets_seconds: Iterable[int],
) -> dict[int, TransferMetrics]:
    """Return metrics keyed by outgoing offset, always including the zero baseline."""
    raise NotImplementedError
