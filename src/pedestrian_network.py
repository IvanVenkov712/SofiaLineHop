"""Public interfaces for pedestrian network construction and routing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .models import Stop, WalkingRoute

if TYPE_CHECKING:
    from networkx import MultiDiGraph


def build_pedestrian_network(place: str) -> MultiDiGraph:
    """Build the OSM walking graph for a named place."""
    raise NotImplementedError


def find_walking_route(
    network: MultiDiGraph, origin: Stop, destination: Stop, walking_speed_mps: float
) -> WalkingRoute | None:
    """Return a walking route at the given speed, or None for disconnected stops."""
    raise NotImplementedError
