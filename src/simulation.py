"""Public interface for simulating one transfer connection."""

from .models import Schedule, SimulationParameters, TransferConnection, TransferOutcome, WalkingRoute


def simulate_transfers(
    schedule: Schedule,
    connection: TransferConnection,
    walking_route: WalkingRoute,
    parameters: SimulationParameters,
    outgoing_offset_seconds: int = 0,
) -> list[TransferOutcome]:
    """Evaluate arrivals at this connection. A positive offset moves departures later."""
    raise NotImplementedError
