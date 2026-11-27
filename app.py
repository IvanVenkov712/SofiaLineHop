"""Streamlit interface for exploring a single public transport transfer."""

from datetime import time
from pathlib import Path
from tempfile import TemporaryDirectory

import folium
import streamlit as st

from src.geopackage import StoredTransfer, write_geopackage
from src.gtfs_loader import load_schedule
from src.models import SimulationParameters
from src.optimization import optimize_offsets
from src.pedestrian_network import build_pedestrian_network, find_walking_route
from src.realtime_view import align_snapshot_interval, operating_schedule, snapshot_picker
from src.results_view import show_results
from src.simulation import simulate_stochastic_transfers
from src.transfers import find_transfers

FEED = Path(__file__).resolve().parent / "data/raw/gtfs"
SNAP_LIMIT_M = 100


@st.cache_resource(max_entries=2, show_spinner="Reading the service-day timetable…")
def timetable(day, feed_version):
    schedule = load_schedule(FEED, day)
    directions = {}
    for trip in schedule.trips:
        available = directions.setdefault(trip.route_id, set())
        if trip.direction_id is not None:
            available.add(trip.direction_id)
    return schedule, directions


@st.cache_resource(show_spinner="Loading Sofia’s walking network. The first download may take several minutes.")
def network():
    return build_pedestrian_network()


@st.cache_data(max_entries=64, show_spinner="Finding connected stops…")
def connections(day, version, incoming, outgoing, incoming_direction, outgoing_direction, limit):
    schedule, _ = timetable(day, version)
    return find_transfers(
        schedule, limit, network=network(), incoming_route_id=incoming, outgoing_route_id=outgoing,
        incoming_direction_id=incoming_direction, outgoing_direction_id=outgoing_direction,
        max_snap_distance_m=SNAP_LIMIT_M,
    )


@st.cache_data(max_entries=64, show_spinner=False)
def walking_route(origin, destination, speed):
    return find_walking_route(network(), origin, destination, speed, max_snap_distance_m=SNAP_LIMIT_M)


def stop_label(stop):
    return f"{stop.name} ({stop.stop_id})"


def transfer_download(origin, destination, transfer):
    with TemporaryDirectory() as directory:
        path = Path(directory) / "transfer.gpkg"
        stops = {stop.stop_id: stop for stop in (origin, destination)}
        write_geopackage(path, stops.values(), [transfer])
        return path.read_bytes()


@st.cache_data(max_entries=64, show_spinner=False)
def map_html(origin, destination, geometry):
    start = (origin.latitude, origin.longitude)
    end = (destination.latitude, destination.longitude)
    points = [(lat, lon) for lon, lat in geometry]
    view = folium.Map(location=start, zoom_start=17, control_scale=True)
    if len(points) > 1:
        folium.PolyLine(points, color="#245fa4", weight=5, tooltip="Walking route").add_to(view)
    if start == end:
        folium.Marker(start, tooltip="Alight and board here").add_to(view)
    else:
        folium.Marker(start, tooltip="Alight here", icon=folium.Icon(color="blue")).add_to(view)
        folium.Marker(end, tooltip="Board here", icon=folium.Icon(color="green")).add_to(view)
    view.fit_bounds([start, end, *points], padding=(24, 24), max_zoom=18)
    return view.get_root().render()


def direction_picker(role, available):
    return st.selectbox(
        f"{role} direction", [None, *sorted(available)],
        format_func=lambda value: "All directions" if value is None else f"Direction {value}",
        disabled=not available,
    )


def seconds(value):
    return value.hour * 3600 + value.minute * 60 + value.second


def main():
    st.set_page_config(page_title="SofiaLineHop")
    st.title("SofiaLineHop")
    st.caption("Explore a walking transfer between two Sofia public transport routes.")
    mode = st.radio("Operating conditions", ["Scheduled", "Realtime-informed"], horizontal=True)
    realtime = mode == "Realtime-informed"
    capture = None
    if realtime:
        with st.expander("GTFS Realtime snapshot", expanded=True):
            capture = snapshot_picker()
        if capture:
            align_snapshot_interval(capture[0].source_timestamp)
    date_col, start_col, end_col = st.columns(3)
    st.session_state.setdefault("start_time", time(7))
    st.session_state.setdefault("end_time", time(9))
    day = date_col.date_input("Service date", key="service_date")
    start = start_col.time_input("From", key="start_time")
    end = end_col.time_input("Until (exclusive)", key="end_time")
    start_seconds, end_seconds = seconds(start), seconds(end)
    if end < start:
        end_seconds += 86400
        st.caption("The interval ends the following morning on the selected GTFS service day.")
    elif end == start:
        st.info("Choose different start and end times.")
        return

    try:
        version = tuple(sorted((p.name, p.stat().st_mtime_ns) for p in FEED.glob("*.txt")))
        schedule, directions = timetable(day, version)
    except FileNotFoundError as exc:
        st.info(f"Place the unpacked Sofia GTFS feed in data/raw/gtfs/. Missing file: {Path(exc.filename).name}")
        return
    except (ValueError, OSError) as exc:
        st.error(f"Could not read the GTFS timetable: {exc}")
        return

    conditions = schedule
    snapshot_key = None
    if capture:
        conditions = operating_schedule(schedule, capture)
        if conditions is not None:
            snapshot_key = (capture[0], capture[2], conditions.issues)
    if len(directions) < 2:
        st.info("Fewer than two routes operate on this service date. Choose another date.")
        return

    def route_label(route_id):
        route = schedule.routes[route_id]
        name = " · ".join(filter(None, (route.short_name, route.long_name)))
        return f"{name} ({route_id})"

    st.subheader("Transfer connection")
    routes = sorted(directions, key=route_label)
    left, right = st.columns(2)
    with left:
        incoming = st.selectbox("Incoming route", routes, format_func=route_label)
        incoming_dir = direction_picker("Incoming", directions[incoming])
    with right:
        outgoing = st.selectbox("Outgoing route", [r for r in routes if r != incoming], format_func=route_label)
        outgoing_dir = direction_picker("Outgoing", directions[outgoing])
    limit = st.number_input("Maximum walking distance (m)", min_value=0, value=500, step=50)
    try:
        pairs = connections(day, version, incoming, outgoing, incoming_dir, outgoing_dir, limit)
    except Exception as exc:
        st.error(f"Could not load or route on the Sofia walking network. Check the local graph cache "
                 f"and internet connection, then retry. Details: {exc}")
        st.button("Retry walking network")
        return
    if not pairs:
        st.info("No connected stops within this walking distance. Increase the distance or change routes or directions.")
        return

    def pair_label(pair):
        return " → ".join(stop_label(schedule.stops[leg.stop_id]) for leg in (pair.incoming, pair.outgoing))

    pair = st.selectbox("Transfer stops (alight → board)", pairs, format_func=pair_label)
    origin = schedule.stops[pair.incoming.stop_id]
    destination = schedule.stops[pair.outgoing.stop_id]
    with st.expander("Simulation parameters"):
        if realtime:
            st.caption("What-if delays are added to the modeled arrival and departure times.")
        left, right = st.columns(2)
        speed = left.number_input("Walking speed (m/s)", min_value=0.1, value=1.4, step=0.1)
        buffer = right.number_input("Minimum boarding buffer (s)", min_value=0, value=0)
        arrival = left.number_input("Incoming arrival delay (s)", min_value=0, value=0)
        departure = right.number_input("Outgoing departure delay (s)", min_value=0, value=0)

    walk = walking_route(origin, destination, speed)
    if walk is None:
        st.warning("No walking route is available for these stops. Select another pair.")
        return
    st.iframe(map_html(origin, destination, walk.geometry), height=350)
    st.caption(f"Walking route · {walk.distance_meters:.0f} m · {walk.duration_seconds / 60:.1f} min "
               "between pedestrian network nodes.")
    st.download_button("Download GeoPackage",
                       data=lambda: transfer_download(origin, destination, StoredTransfer(pair, walk, day, speed)),
                       file_name="transfer.gpkg", mime="application/geopackage+sqlite3", on_click="ignore")

    parameters = SimulationParameters(start_seconds, end_seconds, buffer, arrival, departure)
    shifts = st.slider("Outgoing schedule shifts to evaluate (min)", -15, 15, (-5, 5))
    st.caption("Evaluate each whole-minute shift in the range and the original schedule.")
    selection = (day, version, pair, parameters, walk, shifts, mode, snapshot_key)
    ready = not realtime or (capture is not None and conditions is not None)
    if st.button("Run simulation", type="primary", disabled=not ready) and ready:
        optimization = optimize_offsets(conditions, pair, walk, parameters,
                                        min_offset_seconds=60 * shifts[0],
                                        max_offset_seconds=60 * shifts[1], step_seconds=60)
        outcomes = {}
        for offset in {0, optimization.best_offset_seconds}:
            outcomes[offset], = simulate_stochastic_transfers(
                conditions, pair, walk, parameters, outgoing_offset_seconds=offset)
        st.session_state.result = selection, optimization, outcomes
    result = st.session_state.get("result")
    if ready and result and result[0] == selection:
        _, optimization, outcomes = result
        show_results(optimization, outcomes, parameters)


if __name__ == "__main__":
    main()
