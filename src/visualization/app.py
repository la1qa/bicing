"""Streamlit UI for exploring one Bicing snapshot at a time."""

from datetime import date
import os

import streamlit as st
from streamlit.components.v1 import html

from src.visualization.heatmap import (
    StationObservation,
    Metric,
    gaussian_kde,
    fetch_snapshot,
    render_heatmap,
    snapshot_dates,
)
from src.visualization.distance import distance_accessibility

st.set_page_config(page_title="Bicing availability heatmap", layout="wide")
st.title("Bicing geographical availability heatmap")
st.caption("Continuous KDE surface; station markers are intentionally omitted.")


@st.cache_data(ttl=300)
def cached_snapshot_dates(api_url: str, selected_date: date) -> list[str]:
    """Cache the small date-level snapshot lookup briefly."""
    return snapshot_dates(api_url, selected_date)


@st.cache_data(ttl=300)
def cached_snapshot(api_url: str, timestamp: str) -> tuple[StationObservation, ...]:
    """Cache one complete snapshot so metric changes avoid another API call."""
    return tuple(fetch_snapshot(api_url, timestamp))


@st.cache_data
def cached_kde(
    observations: tuple[StationObservation, ...],
    metric: Metric,
    bandwidth_m: int,
):
    """Cache KDE results for repeated metric and bandwidth selections."""
    return gaussian_kde(list(observations), metric, bandwidth_m)


with st.sidebar:
    api_url = st.text_input(
        "Bicing API URL",
        os.environ.get("BICING_API_URL", "http://127.0.0.1:8000"),
    )
    selected_date = st.date_input("Snapshot date", value=date(2024, 1, 1))
    mode = st.selectbox(
        "Spatial analysis",
        options=["gaussian", "distance"],
        format_func=lambda value: (
            "Gaussian spatial intensity"
            if value == "gaussian"
            else "Straight-line distance accessibility"
        ),
    )
    metric = st.selectbox(
        "Metric",
        options=(
            ["available_bikes", "available_docks"]
            if mode == "gaussian"
            else [
                "mechanical_bikes",
                "ebikes",
                "available_bikes",
                "available_docks",
            ]
        ),
        format_func=lambda value: (
            {
                "mechanical_bikes": "Mechanical bikes",
                "ebikes": "E-bikes",
                "available_bikes": "Total available bikes",
                "available_docks": "Available docks",
            }[value]
        ),
    )
    if mode == "gaussian":
        bandwidth_m = st.slider(
            "Gaussian bandwidth (metres)",
            min_value=100,
            max_value=1000,
            value=250,
            step=50,
        )
    else:
        distance_m = st.slider(
            "Distance threshold (metres)",
            min_value=100,
            max_value=1000,
            value=400,
            step=50,
        )

try:
    timestamps = cached_snapshot_dates(api_url, selected_date)
except Exception as exc:
    st.error(f"Could not retrieve snapshots: {exc}")
    st.stop()

if not timestamps:
    st.info("No stored snapshots are available for this date.")
    st.stop()

selected_timestamp = st.selectbox(
    "Available snapshot time (UTC)",
    timestamps,
    format_func=lambda timestamp: timestamp.replace("T", " "),
)
st.write(f"Selected snapshot: `{selected_timestamp}`")

observations = cached_snapshot(api_url, selected_timestamp)
if mode == "gaussian":
    values, bounds = cached_kde(observations, metric, bandwidth_m)
    legend_caption = None
    render_bandwidth = bandwidth_m
else:
    values, bounds = distance_accessibility(
        list(observations),
        metric,
        distance_m,
    )
    legend_caption = f"{metric.replace('_', ' ').title()} within {distance_m} metres"
    render_bandwidth = distance_m
heatmap = render_heatmap(
    values,
    bounds,
    metric=metric,
    timestamp=selected_timestamp,
    bandwidth_m=render_bandwidth,
    legend_caption=legend_caption,
)
html(heatmap.get_root().render(), height=760, scrolling=False)
st.caption(f"Included {len(observations)} stations with valid coordinates.")
if mode == "distance":
    st.caption(
        "Accessibility is the sum of availability at all stations included "
        "within the selected straight-line distance; it is not a journey count."
    )
