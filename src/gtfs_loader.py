"""Public interface for GTFS ingestion."""

from datetime import date
from pathlib import Path

from .models import Schedule


def load_schedule(gtfs_directory: Path, service_date: date) -> Schedule:
    """Load an unpacked feed for one service date, including calendar exceptions."""
    raise NotImplementedError
