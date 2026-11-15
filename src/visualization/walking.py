"""Cached pedestrian-network accessibility surfaces for Bicing snapshots."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Callable

import networkx as nx
import numpy as np
import osmnx as ox

from src.visualization.heatmap import (
    BARCELONA_BOUNDS,
    PROJECTED_CRS,
    StationObservation,
    _TO_PROJECTED,
)

WALKING_SPEED_MPS = 1.25
MAX_NETWORK_SNAP_DISTANCE_M = 100.0
ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class AccessibilityIndex:
    """Station-to-map-cell reachability independent of availability values."""

    station_ids: tuple[str, ...]
    reachable: np.ndarray
    bounds: tuple[float, float, float, float]
    resolution: int


def load_walking_graph(
    cache_path: str | Path,
    bounds: tuple[float, float, float, float] = BARCELONA_BOUNDS,
):
    """Load or download a projected OSM walking graph for the study area."""
    cache = Path(cache_path)
    if cache.exists():
        graph = ox.load_graphml(cache)
    else:
        west, east, south, north = bounds
        graph = ox.graph_from_bbox(
            (west, south, east, north),
            network_type="walk",
            retain_all=True,
        )
        graph = ox.project_graph(graph, to_crs=PROJECTED_CRS)
        cache.parent.mkdir(parents=True, exist_ok=True)
        ox.save_graphml(graph, cache)
    for _, _, _, data in graph.edges(keys=True, data=True):
        data["travel_time"] = float(data.get("length", 0)) / WALKING_SPEED_MPS
    return graph


def build_reachability_index(
    graph,
    observations: list[StationObservation],
    walking_minutes: int,
    *,
    cache_path: str | Path,
    resolution: int = 180,
    bounds: tuple[float, float, float, float] = BARCELONA_BOUNDS,
    max_snap_distance_m: float = MAX_NETWORK_SNAP_DISTANCE_M,
    progress_callback: ProgressCallback | None = None,
) -> AccessibilityIndex:
    """Build or load a disk-cached station-to-grid reachability matrix.

    Routing is performed once per station for the selected threshold. The
    resulting boolean matrix has one row per station and one column per map
    cell, so later snapshots and metrics only perform a matrix multiplication.
    """
    if walking_minutes <= 0:
        raise ValueError("walking_minutes must be positive")
    if resolution < 2:
        raise ValueError("resolution must be at least 2")
    station_ids = tuple(item.station_id for item in observations)
    cache_file = _reachability_cache_file(
        cache_path,
        observations,
        walking_minutes,
        resolution,
        bounds,
        max_snap_distance_m,
    )
    if cache_file.exists():
        with np.load(cache_file, allow_pickle=False) as loaded:
            reachable = loaded["reachable"]
        if reachable.shape == (len(station_ids), resolution * resolution):
            if progress_callback:
                progress_callback(len(station_ids), len(station_ids))
            return AccessibilityIndex(station_ids, reachable, bounds, resolution)

    node_to_grid, grid_shape = _grid_node_mapping(
        graph, resolution, bounds, max_snap_distance_m
    )
    station_nodes = _station_nodes(graph, observations, max_snap_distance_m)
    reachable = np.zeros((len(observations), resolution * resolution), dtype=bool)
    cutoff_seconds = walking_minutes * 60
    total = len(observations)
    for index, station_node in enumerate(station_nodes):
        if station_node is not None:
            distances = nx.single_source_dijkstra_path_length(
                graph,
                station_node,
                cutoff=cutoff_seconds,
                weight="travel_time",
            )
            for node in distances:
                indices = node_to_grid.get(node)
                if indices:
                    reachable[index, indices] = True
        if progress_callback:
            progress_callback(index + 1, total)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache_file, reachable=reachable)
    return AccessibilityIndex(station_ids, reachable, bounds, grid_shape[0])


def aggregate_accessibility(
    index: AccessibilityIndex,
    observations: list[StationObservation],
    metric: str,
) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """Aggregate one snapshot's availability through a reachability index."""
    values_by_station = {
        observation.station_id: observation.value(metric)
        for observation in observations
    }
    weights = np.asarray([
        max(0.0, float(values_by_station.get(station_id) or 0))
        for station_id in index.station_ids
    ])
    surface = weights @ index.reachable
    return surface.reshape((index.resolution, index.resolution)), index.bounds


def walking_accessibility(
    graph,
    observations: list[StationObservation],
    metric: str,
    walking_minutes: int,
    *,
    resolution: int = 180,
    bounds: tuple[float, float, float, float] = BARCELONA_BOUNDS,
    max_snap_distance_m: float = MAX_NETWORK_SNAP_DISTANCE_M,
    cache_path: str | Path | None = None,
) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """Calculate an accessibility surface using an in-memory temporary index."""
    index = build_reachability_index(
        graph,
        observations,
        walking_minutes,
        cache_path=cache_path or (
            Path.cwd() / "data" / "processed" / "walking.graphml"
        ),
        resolution=resolution,
        bounds=bounds,
        max_snap_distance_m=max_snap_distance_m,
    )
    return aggregate_accessibility(index, observations, metric)


def _grid_node_mapping(
    graph,
    resolution: int,
    bounds: tuple[float, float, float, float],
    max_snap_distance_m: float,
) -> tuple[dict[object, list[int]], tuple[int, int]]:
    west, east, south, north = bounds
    x_min, y_min = _TO_PROJECTED.transform(west, south)
    x_max, y_max = _TO_PROJECTED.transform(east, north)
    grid_x = np.linspace(x_min, x_max, resolution)
    grid_y = np.linspace(y_max, y_min, resolution)
    mesh_x, mesh_y = np.meshgrid(grid_x, grid_y)
    nodes, distances = ox.distance.nearest_nodes(
        graph,
        X=mesh_x.ravel(),
        Y=mesh_y.ravel(),
        return_dist=True,
    )
    node_to_grid: dict[object, list[int]] = {}
    for index, (node, distance) in enumerate(zip(nodes, distances)):
        if float(distance) <= max_snap_distance_m:
            node_to_grid.setdefault(node, []).append(index)
    return node_to_grid, (resolution, resolution)


def _station_nodes(
    graph,
    observations: list[StationObservation],
    max_snap_distance_m: float,
) -> list[object | None]:
    if not observations:
        return []
    x_values, y_values = zip(*[
        _TO_PROJECTED.transform(item.longitude, item.latitude)
        for item in observations
    ])
    nodes, distances = ox.distance.nearest_nodes(
        graph,
        X=np.asarray(x_values),
        Y=np.asarray(y_values),
        return_dist=True,
    )
    return [
        node if float(distance) <= max_snap_distance_m else None
        for node, distance in zip(nodes, distances)
    ]


def _reachability_cache_file(
    graph_cache_path: str | Path,
    observations: list[StationObservation],
    walking_minutes: int,
    resolution: int,
    bounds: tuple[float, float, float, float],
    max_snap_distance_m: float,
) -> Path:
    graph_path = Path(graph_cache_path)
    graph_signature = (
        f"{graph_path}:{graph_path.stat().st_mtime_ns}:{graph_path.stat().st_size}"
        if graph_path.exists()
        else str(graph_path)
    )
    station_signature = "|".join(
        f"{item.station_id}:{item.longitude:.7f}:{item.latitude:.7f}"
        for item in observations
    )
    payload = (
        f"{graph_signature}|{station_signature}|{walking_minutes}|{resolution}|"
        f"{bounds}|{max_snap_distance_m}"
    )
    key = hashlib.sha256(payload.encode()).hexdigest()[:20]
    return graph_path.with_name(f"{graph_path.stem}.accessibility-{key}.npz")
