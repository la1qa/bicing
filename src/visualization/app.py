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
    metric = st.selectbox(
        "Metric",
        options=["available_bikes", "available_docks"],
        format_func=lambda value: (
            "Available bikes (mechanical + electric)"
            if value == "available_bikes"
            else "Available docks"
        ),
    )
    bandwidth_m = st.slider(
        "Gaussian bandwidth (metres)",
        min_value=100,
        max_value=3000,
        value=750,
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
values, bounds = cached_kde(
    observations,
    metric,
    bandwidth_m,
)
heatmap = render_heatmap(
    values,
    bounds,
    metric=metric,
    timestamp=selected_timestamp,
    bandwidth_m=bandwidth_m,
)
html(heatmap.get_root().render(), height=760, scrolling=False)
st.caption(f"Included {len(observations)} stations with valid coordinates.")
