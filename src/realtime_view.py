"""Streamlit controls for live Trip Updates and offline snapshot replay."""

from datetime import datetime, timedelta, time as clock_time
from time import time

import streamlit as st

from . import gtfs_realtime as rt
from .realtime_schedule import integrate_schedule
from .simulation import realtime_window


def timestamp_label(epoch):
    return datetime.fromtimestamp(epoch, rt.SOFIA).strftime("%Y-%m-%d %H:%M:%S %Z")


def snapshot_picker():
    source = st.radio("Snapshot source", ["Live feed", "Saved snapshot"], horizontal=True)
    live = source == "Live feed"
    state_key = "live_snapshot" if live else "saved_snapshot"
    try:
        if live:
            if st.button("Fetch / refresh Trip Updates"):
                st.session_state[state_key] = rt.fetch_snapshot()
        else:
            upload = st.file_uploader("Load snapshot archive", type=["json"])
            if upload is None:
                return None
            st.session_state[state_key] = rt.Snapshot.from_archive(upload.getvalue())
        snapshot = st.session_state.get(state_key)
        if snapshot is None:
            st.info("Fetch Trip Updates to use realtime conditions.")
            return None
        source_time = timestamp_label(snapshot.source_timestamp)
        retrieval_time = timestamp_label(snapshot.retrieved_at)
    except (OSError, OverflowError, ValueError) as exc:
        st.session_state.pop(state_key, None)
        st.error(f"Realtime data unavailable. {exc}")
        return None

    as_of = int(time()) if live else snapshot.retrieved_at
    age = as_of - snapshot.source_timestamp
    basis = "now" if live else "original retrieval (archive replay)"
    st.caption(f"Source · {source_time}  |  Retrieved · {retrieval_time}")
    st.caption(f"Feed age at {basis} · {age} s (limit 90 s)")
    if age < 0 or age > 90:
        st.warning("Stale or future-dated snapshot. Fetch again or load a compatible archive.")
        return None
    if live:
        st.download_button("Save snapshot", snapshot.archive(), f"{snapshot.source_timestamp}.json",
                           mime="application/json", on_click="ignore")
    return snapshot, as_of, source


def align_snapshot_interval(source_timestamp):
    capture_day = datetime.fromtimestamp(source_timestamp, rt.SOFIA).date()
    day = st.session_state.get("service_date") or capture_day
    start = st.session_state.get("start_time")
    end = st.session_state.get("end_time")
    if start is not None and end is not None:
        first, last = realtime_window(day, source_timestamp)
        start_s = start.hour * 3600 + start.minute * 60 + start.second
        end_s = end.hour * 3600 + end.minute * 60 + end.second + (86400 if end < start else 0)
        if first <= start_s < end_s <= last:
            return

    # Fit the minute-resolution controls inside the forecast, including overnight trips.
    for day in (capture_day, capture_day - timedelta(days=1), capture_day + timedelta(days=1)):
        first, last = realtime_window(day, source_timestamp)
        start_min = max(0, (first + 59) // 60)
        end_min = last // 60
        if start_min < 1440 and start_min < end_min:
            st.session_state.service_date = day
            st.session_state.start_time = clock_time(*divmod(start_min, 60))
            st.session_state.end_time = clock_time(*divmod(end_min % 1440, 60))
            return


def operating_schedule(schedule, capture):
    snapshot, as_of, _ = capture
    view = integrate_schedule(schedule, snapshot, as_of=as_of)
    coverage = view.coverage()
    with st.expander("Snapshot coverage across the full service day"):
        st.caption(f"{coverage.matched_trips:,}/{coverage.total_trips:,} trips matched · "
                   f"{coverage.reported_events + coverage.propagated_events:,}/{coverage.total_events:,} "
                   "arrival and departure times predicted")
        if coverage.fallback_events:
            st.caption(f"{coverage.fallback_events:,} arrival and departure times use the timetable.")
        if coverage.unavailable_events:
            st.caption(f"{coverage.unavailable_events:,} arrival and departure times are unavailable.")
        if view.issues:
            st.caption(f"Snapshot diagnostics ({len(view.issues):,})")
            st.text("\n".join(view.issues[:20]))
            if len(view.issues) > 20:
                st.caption("Showing the first 20 diagnostics.")
    if not coverage.matched_trips:
        st.warning("No usable Trip Updates match this service date and timetable.")
        return None
    return view
