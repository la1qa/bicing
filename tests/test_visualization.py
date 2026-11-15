import numpy as np

from src.visualization.heatmap import (
    StationObservation,
    fetch_snapshot,
    gaussian_kde,
)


def test_gaussian_kde_uses_projected_bandwidth_and_metric_weights():
    observations = [
        StationObservation("1", 2.15, 41.39, 10, 2, 4),
        StationObservation("2", 2.16, 41.40, 0, 3, 8),
    ]
    values, bounds = gaussian_kde(
        observations,
        "available_bikes",
        bandwidth_m=500,
        resolution=32,
    )
    assert values.shape == (32, 32)
    assert values.max() > 0
    assert bounds == (2.05, 2.25, 41.30, 41.47)


def test_gaussian_kde_ignores_missing_metric_values():
    observation = StationObservation("1", 2.15, 41.39, None, None, None)
    values, _ = gaussian_kde([observation], "available_docks", 500, resolution=8)
    assert np.all(values == 0)


def test_fetch_snapshot_makes_one_request_and_skips_invalid_coordinates(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "items": [
                    {
                        "station_id": "1",
                        "latitude": 41.39,
                        "longitude": 2.15,
                        "mechanical_bikes_available": 4,
                        "ebikes_available": 2,
                        "docks_available": 8,
                    },
                    {"station_id": "2", "latitude": None, "longitude": 2.16},
                ]
            }

    calls = []
    monkeypatch.setattr(
        "src.visualization.heatmap.requests.get",
        lambda url, params, timeout: calls.append((url, params, timeout)) or Response(),
    )
    observations = fetch_snapshot("http://api.test", "2024-01-01T00:00:00Z")
    assert len(calls) == 1
    assert calls[0][1]["limit"] == 5000
    assert len(observations) == 1
    assert observations[0].value("available_bikes") == 6
