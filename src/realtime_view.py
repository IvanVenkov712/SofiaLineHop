"""Streamlit controls for live Trip Updates and offline snapshot replay."""

from datetime import datetime
from time import time

import streamlit as st

from . import gtfs_realtime as rt
from .realtime_schedule import integrate_schedule
from .simulation import validate_realtime_window


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


def operating_schedule(schedule, capture, start, end):
    snapshot, as_of, _ = capture
    try:
        validate_realtime_window(schedule.service_date, snapshot.source_timestamp, start, end)
    except ValueError:
        first = timestamp_label(snapshot.source_timestamp - 90)
        last = timestamp_label(snapshot.source_timestamp + 3600)
        st.warning(f"Incompatible service date or period. Choose an interval between {first} and {last}.")
        return None
    view = integrate_schedule(schedule, snapshot, as_of=as_of)
    coverage = view.coverage()
    st.caption(f"Service-day coverage · {coverage.matched_trips}/{coverage.total_trips} trips matched · "
               f"{coverage.reported_events + coverage.propagated_events}/{coverage.total_events} "
               "arrival and departure times predicted")
    if view.issues:
        with st.expander(f"Snapshot diagnostics ({len(view.issues)})"):
            st.text("\n".join(view.issues[:20]))
            if len(view.issues) > 20:
                st.caption("Showing the first 20 diagnostics.")
    if not coverage.matched_trips:
        st.warning("No usable Trip Updates match this service date and timetable.")
        return None
    if coverage.fallback_events or coverage.unavailable_events:
        st.warning(f"Incomplete timing coverage. {coverage.fallback_events} events use timetable times. "
                   f"{coverage.unavailable_events} have no usable time.")
    return view
