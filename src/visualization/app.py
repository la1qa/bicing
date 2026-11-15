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
from src.visualization.walking import (
    aggregate_accessibility,
    build_reachability_index,
    load_walking_graph,
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


@st.cache_resource
def cached_walking_graph(cache_path: str):
    """Cache the downloaded/projected pedestrian graph for the session."""
    return load_walking_graph(cache_path)


with st.sidebar:
    api_url = st.text_input(
        "Bicing API URL",
        os.environ.get("BICING_API_URL", "http://127.0.0.1:8000"),
    )
    selected_date = st.date_input("Snapshot date", value=date(2024, 1, 1))
    mode = st.selectbox(
        "Spatial analysis",
        options=["gaussian", "walking"],
        format_func=lambda value: (
            "Gaussian spatial intensity"
            if value == "gaussian"
            else "Walking-time accessibility"
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
            max_value=3000,
            value=750,
            step=50,
        )
    else:
        walking_minutes = st.selectbox(
            "Walking-time threshold (minutes)",
            options=[2, 5, 10, 15],
            index=1,
        )
        graph_cache_path = st.text_input(
            "Walking graph cache",
            os.environ.get(
                "BICING_WALKING_GRAPH_CACHE",
                "data/processed/barcelona_walk.graphml",
            ),
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
    with st.status("Preparing walking accessibility...", expanded=True) as status:
        status.write("Loading or downloading the pedestrian network...")
        graph = cached_walking_graph(graph_cache_path)
        progress = st.progress(0, text="Calculating station reachability...")

        def update_progress(done: int, total: int) -> None:
            progress.progress(
                done / total if total else 1.0,
                text=f"Calculating station reachability ({done}/{total})",
            )

        index = build_reachability_index(
            graph,
            list(observations),
            walking_minutes,
            cache_path=graph_cache_path,
            progress_callback=update_progress,
        )
        values, bounds = aggregate_accessibility(index, list(observations), metric)
        progress.empty()
        status.update(label="Walking accessibility ready", state="complete")
    legend_caption = f"{metric.replace('_', ' ').title()} within {walking_minutes} minutes"
    render_bandwidth = walking_minutes * 60
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
if mode == "walking":
    st.caption(
        "Accessibility is the sum of availability at all stations reachable "
        "within the selected walking time; it is not a journey count."
    )
