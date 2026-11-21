"""Streamlit UI for exploring one Bicing snapshot at a time."""

import os
import calendar
from datetime import date, datetime, timezone

import streamlit as st
from streamlit.components.v1 import html

from src.visualization.heatmap import (
    StationObservation,
    Metric,
    gaussian_kde,
    fetch_snapshot,
    render_heatmap,
    snapshot_dates_for_range,
)
from src.visualization.distance import distance_accessibility

st.set_page_config(page_title="Bicing availability heatmap", layout="wide")
st.title("Bicing geographical availability heatmap")
st.caption("Continuous KDE surface; station markers are intentionally omitted.")


@st.cache_data(ttl=300)
def cached_snapshot_dates_for_range(
    api_url: str,
    start: datetime,
    end: datetime,
) -> list[str]:
    """Cache snapshot timestamps for one month range."""
    return snapshot_dates_for_range(api_url, start, end)


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
    api_url = os.environ.get("BICING_API_URL", "http://127.0.0.1:8000")
    st.subheader("Snapshot")
    year = st.selectbox(
        "Year",
        options=list(range(2023, date.today().year + 1)),
        index=min(1, date.today().year - 2023),
    )
    month = st.selectbox(
        "Month",
        options=list(range(1, 13)),
        format_func=lambda value: calendar.month_name[value],
        index=0,
    )
    load_month = st.button("Load month")
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

if load_month:
    month_start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        month_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        month_end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    try:
        st.session_state["snapshot_timestamps"] = cached_snapshot_dates_for_range(
            api_url,
            month_start,
            month_end,
        )
        st.session_state["snapshot_calendar_month"] = (year, month)
        st.session_state.pop("snapshot_selected_date", None)
        st.session_state.pop("snapshot_selected_timestamp", None)
    except Exception as exc:
        st.error(f"Could not retrieve snapshots: {exc}")
        st.stop()

timestamps = st.session_state.get("snapshot_timestamps", [])

calendar_month = st.session_state.get("snapshot_calendar_month")
if calendar_month:
    calendar_year, calendar_month_number = calendar_month
    st.subheader(f"{calendar.month_name[calendar_month_number]} {calendar_year}")
    available_dates = {
        datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date()
        for timestamp in timestamps
    }
    selected_date = st.session_state.get("snapshot_selected_date")
    month_days = calendar.monthcalendar(calendar_year, calendar_month_number)
    day_names = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    header_columns = st.columns(7)
    for column, name in enumerate(day_names):
        header_columns[column].markdown(f"**{name}**")
    for week in month_days:
        columns = st.columns(7)
        for column, day in enumerate(week):
            if day == 0:
                continue
            day_date = date(calendar_year, calendar_month_number, day)
            available = day_date in available_dates
            if columns[column].button(
                str(day),
                key=f"snapshot-day-{day_date.isoformat()}",
                disabled=not available,
            ):
                st.session_state["snapshot_selected_date"] = day_date

selected_date = st.session_state.get("snapshot_selected_date")
if not selected_date:
    st.info("Choose an available day.")
    st.stop()

day_timestamps = [
    timestamp
    for timestamp in timestamps
    if datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date() == selected_date
]
minute_options = sorted({
    datetime.fromisoformat(timestamp.replace("Z", "+00:00")).strftime("%H:%M")
    for timestamp in day_timestamps
})
selected_minute = st.selectbox(
    "Time (UTC)",
    minute_options,
)
selected_hour, selected_minute_number = map(int, selected_minute.split(":"))
matching_timestamp = next(
    timestamp
    for timestamp in day_timestamps
    if datetime.fromisoformat(timestamp.replace("Z", "+00:00")).hour == selected_hour
    and datetime.fromisoformat(timestamp.replace("Z", "+00:00")).minute == selected_minute_number
)
selected_timestamp = matching_timestamp

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
