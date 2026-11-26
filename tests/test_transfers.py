from datetime import date

import networkx as nx
import pytest

from src.analytics import summarize_transfers, summarize_transfers_by_interval
from src.gtfs_loader import load_schedule
from src.models import ScheduledEvent, SimulationParameters
from src.optimization import optimize_offsets
from src.pedestrian_network import find_walking_route
from src.simulation import DelayModel, simulate_stochastic_transfers, simulate_transfers
from src.transfers import find_transfers, get_transfer_events


@pytest.fixture
def feed(tmp_path):
    tables = {
        "stops": ("stop_id,stop_name,stop_lat,stop_lon",
                  "X,Terminal,42.7,23.3", "A,Square,42.7,23.30", "B,Park,42.7,23.31",
                  "C,Hill,42.7,23.32", "D,Branch,42.7,23.33"),
        "routes": ("route_id,route_short_name", "red,R", "blue,B"),
        "trips": ("route_id,service_id,trip_id,direction_id",
                  "red,s,r,0", "blue,s,b,1", "blue,s,reverse,0"),
        "calendar_dates": ("service_id,date,exception_type", "s,20261123,1"),
        "stop_times": (
            "trip_id,stop_sequence,stop_id,arrival_time,departure_time,drop_off_type,pickup_type",
            "r,1,X,24:00:00,24:00:00,,", "r,2,A,25:00:00,25:00:05,,",
            "r,3,C,25:01:00,25:01:00,1,", "r,4,A,25:02:00,25:02:00,,",
            "r,5,D,25:03:00,25:03:00,,",
            "b,1,B,24:59:00,25:00:00,,", "b,2,A,,,,", "b,3,A,25:01:00,25:01:00,,1",
            "b,4,B,25:01:55,25:02:00,,", "b,5,X,25:03:00,25:03:00,,",
            "reverse,1,C,25:00:00,25:00:00,,", "reverse,2,X,25:02:00,25:02:00,,",
        ),
    }
    for name, rows in tables.items():
        (tmp_path / f"{name}.txt").write_text("\n".join(rows), encoding="utf-8")
    return tmp_path


@pytest.fixture
def graph():
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    for node in range(4):
        graph.add_node(node, x=23.30 + node / 100, y=42.7)
    graph.add_edge(0, 1, length=120)
    graph.add_edge(0, 2, length=40)
    graph.add_edge(2, 1, length=60)
    return graph


DAY = date(2026, 11, 23)


def candidates(schedule, graph, limit, direction=1):
    return find_transfers(schedule, limit, network=graph, incoming_route_id="red",
                          incoming_direction_id=0, outgoing_route_id="blue",
                          outgoing_direction_id=direction)


def pairs(connections):
    return [(c.incoming.stop_id, c.outgoing.stop_id) for c in connections]


def test_discover_active_route_stops(feed, graph):
    schedule = load_schedule(feed, DAY)
    assert pairs(candidates(schedule, graph, 0)) == [("A", "A")]
    assert pairs(candidates(schedule, graph, 99)) == [("A", "A")]
    assert pairs(candidates(schedule, graph, 100)) == [("A", "A"), ("A", "B")]
    assert pairs(candidates(schedule, graph, 100, None)) == [("A", "A"), ("A", "B"), ("A", "C")]
    assert candidates(load_schedule(feed, date(2026, 11, 24)), graph, 100) == []
    # Adding a path from an isolated branch makes its terminal arrival a candidate.
    graph.add_edge(3, 1, length=50)
    assert pairs(candidates(schedule, graph, 50)) == [("A", "A"), ("D", "B")]


def test_service_day_events(feed, graph):
    schedule = load_schedule(feed, DAY)
    clipped = load_schedule(feed, DAY, start_seconds=90000, end_seconds=90121)
    assert pairs(candidates(clipped, graph, 100)) == [("A", "B")]
    same_stop, across = candidates(schedule, graph, 100)
    events = get_transfer_events(schedule, across, 90000, 90120)
    assert events.arrivals == (ScheduledEvent(90000, "r", 2),)
    assert events.departures == (ScheduledEvent(90000, "b", 1),)
    events = get_transfer_events(schedule, across, 90000, 90121)
    assert events.arrivals[-1] == ScheduledEvent(90120, "r", 4)
    assert events.departures[-1] == ScheduledEvent(90120, "b", 4)
    assert get_transfer_events(schedule, same_stop, 90000, 90121).departures == ()
    with pytest.raises(ValueError):
        get_transfer_events(schedule, across, 10, 10)


@pytest.mark.parametrize("limit", [-1, float("nan"), float("inf")])
def test_invalid_distance(feed, graph, limit):
    with pytest.raises(ValueError, match="distance"):
        candidates(load_schedule(feed, DAY), graph, limit)


@pytest.mark.parametrize("arrival_delay", [0, 61])
def test_overnight_transfer_workflow(feed, graph, arrival_delay):
    schedule = load_schedule(feed, DAY)
    pair = next(c for c in candidates(schedule, graph, 100)
                if c.incoming.stop_id == "A" and c.outgoing.stop_id == "B")
    walk = find_walking_route(graph, schedule.stops[pair.incoming.stop_id],
                              schedule.stops[pair.outgoing.stop_id], walking_speed_mps=2)
    assert walk.node_ids == (0, 2, 1)
    assert (walk.distance_meters, walk.duration_seconds) == (100, 50)
    parameters = SimulationParameters(90000, 90180, minimum_buffer_seconds=10)
    args = schedule, pair, walk, parameters

    # Visits at 25:00 and 25:02. Only the first can walk 50 s, allow 10 s
    # for boarding, and catch the 25:02 departure before the 25:03 horizon.
    scheduled = simulate_transfers(*args)
    assert [(o.successful, o.waiting_seconds, o.total_duration_seconds) for o in scheduled] == [
        (True, 70, 120), (False, None, None)]
    delays = DelayModel(arrival_delay, arrival_delay)
    outcomes, = simulate_stochastic_transfers(*args, arrival_delay=delays)
    metrics = summarize_transfers(outcomes)
    bins = summarize_transfers_by_interval(outcomes, 60)
    assert list(bins) == [90000, 90120]
    assert bins[90120].incomplete_rate == 1
    result = optimize_offsets(*args, min_offset_seconds=-60, max_offset_seconds=0,
                              step_seconds=60, arrival_delay=delays)
    assert result.scenarios[0] == metrics
    if arrival_delay:
        # Ready at 25:02:01, one second after the intended vehicle departs.
        assert metrics.missed_connection_rate == metrics.incomplete_rate == 1
        assert metrics.mean_waiting_seconds is None
        assert result.best_offset_seconds == 0
    else:
        assert metrics == summarize_transfers(scheduled)
        assert metrics.successful_rate == 0.5
        assert result.best_offset_seconds == -60
        best = result.scenarios[-60]
        assert (best.mean_waiting_seconds, best.mean_total_duration_seconds) == (10, 60)
        assert best.successful_rate == 0.5
