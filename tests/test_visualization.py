from datetime import date, datetime, timezone

import numpy as np

from src.visualization.heatmap import (
    StationObservation,
    fetch_snapshot,
    gaussian_kde,
    snapshot_dates,
    snapshot_dates_for_range,
)


def test_snapshot_dates_queries_only_the_selected_day(monkeypatch):
    calls = []

    class Response:
        def __init__(self, items):
            self.payload = {"items": items}

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    def fake_get(url, params, timeout):
        calls.append((url, params, timeout))
        return Response([{"timestamp": "2024-01-02T00:00:00Z"}])

    monkeypatch.setattr(
        "src.visualization.heatmap.requests.get",
        fake_get,
    )

    timestamps = snapshot_dates("http://api.test", date(2024, 1, 2))

    assert timestamps == ["2024-01-02T00:00:00Z"]
    assert calls[0][1]["start"].startswith("2024-01-02")
    assert calls[0][1]["end"].startswith("2024-01-03")


def test_snapshot_range_fetches_all_pages(monkeypatch):
    calls = []

    class Response:
        def __init__(self, items):
            self.payload = {"items": items}

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    def fake_get(url, params, timeout):
        calls.append(params)
        if params["offset"] == 0:
            items = [{"timestamp": f"2024-01-{day:02d}T00:00:00Z"} for day in range(1, 501)]
        else:
            items = [{"timestamp": "2024-02-01T00:00:00Z"}]
        return Response(items)

    monkeypatch.setattr("src.visualization.heatmap.requests.get", fake_get)

    timestamps = snapshot_dates_for_range(
        "http://api.test",
        datetime(2024, 1, 1, tzinfo=timezone.utc),
        datetime(2024, 2, 1, tzinfo=timezone.utc),
    )

    assert len(timestamps) == 501
    assert [call["offset"] for call in calls] == [0, 500]


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
