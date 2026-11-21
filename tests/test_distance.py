import pytest

from src.visualization.heatmap import StationObservation
from src.visualization.distance import distance_accessibility


def test_distance_accessibility_adds_values_within_straight_line_threshold():
    observations = [
        StationObservation("1", 2.15, 41.39, 3, 2, 4),
        StationObservation("2", 2.16, 41.40, 4, 1, 7),
    ]

    values, _ = distance_accessibility(
        observations,
        "available_bikes",
        distance_m=5000,
        resolution=8,
        bounds=(2.149, 2.151, 41.389, 41.391),
    )

    assert values.max() == 10


def test_distance_accessibility_rejects_non_positive_threshold():
    with pytest.raises(ValueError, match="distance_m must be positive"):
        distance_accessibility([], "available_bikes", 0)
