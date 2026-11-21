"""Straight-line distance accessibility surfaces for Bicing snapshots."""

import numpy as np

from src.visualization.heatmap import (
    BARCELONA_BOUNDS,
    StationObservation,
    _TO_PROJECTED,
)


def distance_accessibility(
    observations: list[StationObservation],
    metric: str,
    distance_m: float,
    *,
    resolution: int = 180,
    bounds: tuple[float, float, float, float] = BARCELONA_BOUNDS,
) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """Sum station availability within a straight-line metre threshold."""
    if distance_m <= 0:
        raise ValueError("distance_m must be positive")
    if resolution < 2:
        raise ValueError("resolution must be at least 2")

    west, east, south, north = bounds
    x_min, y_min = _TO_PROJECTED.transform(west, south)
    x_max, y_max = _TO_PROJECTED.transform(east, north)
    grid_x = np.linspace(x_min, x_max, resolution)
    grid_y = np.linspace(y_max, y_min, resolution)
    mesh_x, mesh_y = np.meshgrid(grid_x, grid_y)
    values = np.zeros_like(mesh_x, dtype=float)

    for observation in observations:
        weight = observation.value(metric)
        if weight is None or weight < 0:
            continue
        station_x, station_y = _TO_PROJECTED.transform(
            observation.longitude,
            observation.latitude,
        )
        distance_squared = (
            (mesh_x - station_x) ** 2
            + (mesh_y - station_y) ** 2
        )
        values += np.where(distance_squared <= distance_m**2, weight, 0)

    return values, bounds


