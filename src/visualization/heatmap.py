"""Snapshot retrieval and projected Gaussian KDE rendering for Bicing."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal

import folium
from folium.raster_layers import ImageOverlay
import numpy as np
from PIL import Image
import requests
from branca.colormap import LinearColormap
from pyproj import Transformer

Metric = Literal[
    "mechanical_bikes",
    "ebikes",
    "available_bikes",
    "available_docks",
]
BARCELONA_BOUNDS = (2.05, 2.25, 41.30, 41.47)
PROJECTED_CRS = "EPSG:25831"
WGS84 = "EPSG:4326"
_TO_PROJECTED = Transformer.from_crs(WGS84, PROJECTED_CRS, always_xy=True)


@dataclass(frozen=True)
class StationObservation:
    """One station's position and values from one snapshot."""

    station_id: str
    longitude: float
    latitude: float
    mechanical_bikes: float | None
    ebikes: float | None
    docks: float | None

    def value(self, metric: Metric) -> float | None:
        """Return the selected availability metric, preserving missing data."""
        if metric == "mechanical_bikes":
            return self.mechanical_bikes
        if metric == "ebikes":
            return self.ebikes
        if metric == "available_docks":
            return self.docks
        values = [value for value in (self.mechanical_bikes, self.ebikes) if value is not None]
        return sum(values) if values else None


def _api_json(base_url: str, path: str, params: dict[str, str | int]) -> dict:
    response = requests.get(f"{base_url.rstrip('/')}{path}", params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Bicing API returned a non-object JSON response")
    return payload


def snapshot_dates(base_url: str, selected_date: date) -> list[str]:
    """Return snapshot timestamps available on one UTC calendar date."""
    start = datetime.combine(selected_date, datetime.min.time(), tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    payload = _api_json(
        base_url,
        "/snapshots",
        {
            "start": start.isoformat().replace("+00:00", "Z"),
            "end": end.isoformat().replace("+00:00", "Z"),
            "limit": 500,
        },
    )
    return [
        item["timestamp"]
        for item in payload.get("items", [])
        if isinstance(item, dict) and item.get("timestamp")
    ]


def snapshot_dates_for_range(
    base_url: str,
    start: datetime,
    end: datetime,
) -> list[str]:
    """Return snapshot timestamps in an explicit UTC range."""
    timestamps: list[str] = []
    limit = 500
    offset = 0
    while True:
        payload = _api_json(
            base_url,
            "/snapshots",
            {
                "start": start.isoformat().replace("+00:00", "Z"),
                "end": end.isoformat().replace("+00:00", "Z"),
                "limit": limit,
                "offset": offset,
            },
        )
        items = payload.get("items", [])
        if not isinstance(items, list):
            break
        timestamps.extend([
            item["timestamp"]
            for item in items
            if isinstance(item, dict) and item.get("timestamp")
        ])
        if len(items) < limit:
            break
        offset += limit
    return timestamps


def fetch_snapshot(base_url: str, timestamp: str) -> list[StationObservation]:
    """Fetch one complete snapshot in one API request."""
    payload = _api_json(
        base_url,
        f"/snapshots/{timestamp}",
        {"limit": 5000},
    )
    observations = []
    for item in payload.get("items", []):
        try:
            longitude = float(item["longitude"])
            latitude = float(item["latitude"])
        except (KeyError, TypeError, ValueError):
            continue
        observations.append(StationObservation(
            station_id=str(item["station_id"]),
            longitude=longitude,
            latitude=latitude,
            mechanical_bikes=_number(item.get("mechanical_bikes_available")),
            ebikes=_number(item.get("ebikes_available")),
            docks=_number(item.get("docks_available")),
        ))
    return observations


def gaussian_kde(
    observations: list[StationObservation],
    metric: Metric,
    bandwidth_m: float,
    *,
    resolution: int = 180,
    bounds: tuple[float, float, float, float] = BARCELONA_BOUNDS,
) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """Calculate weighted Gaussian KDE values on a projected metre grid.

    The returned array is ordered north-to-south for direct map image overlay.
    Values are sums of availability-weighted kernels, not probability density.
    """
    if bandwidth_m <= 0:
        raise ValueError("bandwidth_m must be positive")
    if resolution < 2:
        raise ValueError("resolution must be at least 2")
    west, east, south, north = bounds
    x_min, y_min = _TO_PROJECTED.transform(west, south)
    x_max, y_max = _TO_PROJECTED.transform(east, north)
    points = [
        (_TO_PROJECTED.transform(item.longitude, item.latitude), item.value(metric))
        for item in observations
    ]
    points = [(point, value) for point, value in points if value is not None and value >= 0]
    if not points:
        return np.zeros((resolution, resolution), dtype=float), bounds
    station_xy = np.asarray([point for point, _ in points], dtype=float)
    weights = np.asarray([value for _, value in points], dtype=float)
    grid_x = np.linspace(x_min, x_max, resolution)
    grid_y = np.linspace(y_max, y_min, resolution)
    mesh_x, mesh_y = np.meshgrid(grid_x, grid_y)
    values = np.zeros_like(mesh_x)
    for start in range(0, len(station_xy), 128):
        chunk = station_xy[start:start + 128]
        distances = (
            (mesh_x[..., None] - chunk[:, 0]) ** 2
            + (mesh_y[..., None] - chunk[:, 1]) ** 2
        )
        values += np.sum(
            np.exp(-0.5 * distances / bandwidth_m**2)
            * weights[start:start + 128],
            axis=-1,
        )
    return values, bounds


def render_heatmap(
    values: np.ndarray,
    bounds: tuple[float, float, float, float],
    *,
    metric: Metric,
    timestamp: str,
    bandwidth_m: float,
    legend_caption: str | None = None,
) -> folium.Map:
    """Render a KDE grid as a smooth Folium image overlay."""
    west, east, south, north = bounds
    center = [(south + north) / 2, (west + east) / 2]
    fmap = folium.Map(location=center, zoom_start=12, tiles="OpenStreetMap")
    maximum = float(values.max())
    if maximum > 0:
        rgba = _gradient(values / maximum)
        image = Image.fromarray(rgba, mode="RGBA")
        ImageOverlay(
            image=np.asarray(image),
            bounds=[[south, west], [north, east]],
            opacity=0.62,
            interactive=False,
            cross_origin=False,
            zindex=2,
        ).add_to(fmap)
        LinearColormap(
            colors=["#313695", "#74add1", "#fee090", "#f46d43", "#a50026"],
            vmin=0,
            vmax=maximum,
            caption=legend_caption or _metric_label(metric),
        ).add_to(fmap)
    folium.LayerControl().add_to(fmap)
    fmap.get_root().header.add_child(
        folium.Element(
            f"<meta name='bicing-snapshot' content='{timestamp}; bandwidth={bandwidth_m}m'>"
        )
    )
    return fmap


def _number(value: object) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _gradient(values: np.ndarray) -> np.ndarray:
    stops = np.asarray([
        [49, 54, 149],
        [116, 173, 209],
        [254, 224, 144],
        [244, 109, 67],
        [165, 0, 38],
    ], dtype=float)
    positions = np.linspace(0, 1, len(stops))
    clipped = np.clip(values, 0, 1)
    channels = [
        np.interp(clipped, positions, stops[:, channel])
        for channel in range(3)
    ]
    rgba = np.stack(channels + [np.where(values > 0, 220, 0)], axis=-1)
    return rgba.astype(np.uint8)


def _metric_label(metric: Metric) -> str:
    return {
        "mechanical_bikes": "Mechanical bikes",
        "ebikes": "E-bikes",
        "available_bikes": "Available bikes (mechanical + electric)",
        "available_docks": "Available docks",
    }[metric]
