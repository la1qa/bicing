import networkx as nx

from src.visualization.heatmap import PROJECTED_CRS, StationObservation, _TO_PROJECTED
from src.visualization.walking import (
    build_reachability_index,
    walking_accessibility,
)


def _graph_and_observations():
    x, y = _TO_PROJECTED.transform(2.15, 41.39)
    graph = nx.MultiDiGraph(crs=PROJECTED_CRS)
    graph.add_node(1, x=x, y=y)
    graph.add_node(2, x=x + 100, y=y)
    graph.add_edge(1, 2, length=100.0, travel_time=80.0)
    graph.add_edge(2, 1, length=100.0, travel_time=80.0)
    observations = [
        StationObservation("1", 2.15, 41.39, 3, 2, 4),
        StationObservation("2", 2.15, 41.39, 4, 1, 7),
    ]
    return graph, observations


def test_walking_accessibility_adds_overlapping_station_values(tmp_path):
    graph, observations = _graph_and_observations()

    values, _ = walking_accessibility(
        graph,
        observations,
        "available_bikes",
        walking_minutes=5,
        resolution=8,
        bounds=(2.149, 2.151, 41.389, 41.391),
        max_snap_distance_m=500,
        cache_path=tmp_path / "walking.graphml",
    )

    assert values.max() == 10


def test_reachability_index_reuses_disk_cache(tmp_path, monkeypatch):
    graph, observations = _graph_and_observations()
    calls = 0
    original = nx.single_source_dijkstra_path_length

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        "src.visualization.walking.nx.single_source_dijkstra_path_length",
        counted,
    )
    arguments = {
        "cache_path": tmp_path / "walking.graphml",
        "resolution": 8,
        "bounds": (2.149, 2.151, 41.389, 41.391),
        "max_snap_distance_m": 500,
    }

    build_reachability_index(graph, observations, 5, **arguments)
    build_reachability_index(graph, observations, 5, **arguments)

    assert calls == len(observations)


def test_reachability_index_rebuilds_for_new_threshold(tmp_path, monkeypatch):
    graph, observations = _graph_and_observations()
    calls = 0
    original = nx.single_source_dijkstra_path_length

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        "src.visualization.walking.nx.single_source_dijkstra_path_length",
        counted,
    )
    arguments = {
        "cache_path": tmp_path / "walking.graphml",
        "resolution": 8,
        "bounds": (2.149, 2.151, 41.389, 41.391),
        "max_snap_distance_m": 500,
    }

    build_reachability_index(graph, observations, 5, **arguments)
    build_reachability_index(graph, observations, 10, **arguments)

    assert calls == len(observations) * 2
