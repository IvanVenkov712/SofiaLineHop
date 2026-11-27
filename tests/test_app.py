"""Exercise the Streamlit workflow offline with a small service-day timetable."""

from datetime import time, timedelta

import networkx as nx
import pytest
from google.transit import gtfs_realtime_pb2 as gtfs
from streamlit.testing.v1 import AppTest

from src import gtfs_loader, gtfs_realtime, pedestrian_network, realtime_view
from src.models import Route, Schedule, Stop, StopTime, Trip


@pytest.fixture
def app(monkeypatch):
    stops = {
        "a": Stop("a", "Alight", 42.70, 23.30),
        "b": Stop("b", "Board", 42.70, 23.31),
    }
    routes = {key: Route(key, key, "") for key in ("1", "2")}
    trips = (
        Trip("in", "1", 0, (StopTime("a", 1, 28800, 28800),)),
        Trip("out", "2", 1, (StopTime("b", 1, 29100, 29100),)),
    )
    graph = nx.MultiDiGraph(crs="epsg:4326")
    for index, stop in enumerate(stops.values()):
        graph.add_node(index, x=stop.longitude, y=stop.latitude)
    graph.add_edge(0, 1, length=100)
    monkeypatch.setattr(gtfs_loader, "load_schedule", lambda path, day: Schedule(day, stops, routes, trips))
    monkeypatch.setattr(pedestrian_network, "build_pedestrian_network", lambda: graph)

    return AppTest.from_file("../app.py", default_timeout=30).run()


def test_transfer_workflow(app):
    assert not app.exception
    assert app.selectbox[-1].options == ["Alight (a) → Board (b)"]
    assert "L.polyline" in app.get("iframe")[0].proto.srcdoc
    app.button[0].click().run()
    assert [metric.value for metric in app.metric[:2]] == ["1", "100.0%"]
    assert len(app.get("plotly_chart")) == 2
    comparison, scenarios = (table.value for table in app.dataframe)
    assert comparison.columns.tolist() == ["Original", "Optimized (-3 min)"]
    assert comparison.loc["Mean wait (min)", "Original"] > comparison.loc["Mean wait (min)", "Optimized (-3 min)"]
    assert scenarios["Outgoing shift (min)"].tolist() == list(range(-5, 6))
    app.selectbox[-1].select("Completed (%)").run()
    assert not app.exception
    assert len(app.get("plotly_chart")) == 2
    app.number_input[3].set_value(300).run()
    assert not app.metric
    app.button[0].click().run()
    assert app.metric[1].value == "0.0%"


def test_realtime_workflow(app, monkeypatch):
    day = app.date_input[0].value
    epoch = gtfs_realtime.service_day_origin(day) + 28800
    feed = gtfs.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = epoch
    entity = feed.entity.add(id="incoming")
    entity.trip_update.trip.trip_id = "in"
    entity.trip_update.trip.start_date = day.strftime("%Y%m%d")
    entity.trip_update.stop_time_update.add(stop_sequence=1).arrival.delay = 30
    snapshot = gtfs_realtime.Snapshot(feed.SerializeToString(), epoch + 1)
    monkeypatch.setattr(gtfs_realtime, "fetch_snapshot", lambda: snapshot)
    monkeypatch.setattr(realtime_view, "time", lambda: epoch + 1)
    app.radio[0].set_value("Realtime-informed").run()
    assert app.button[-1].disabled
    app.button[0].click().run()
    assert any("Incompatible service date or period" in w.value for w in app.warning)
    app.time_input[0].set_value(time(8)).run()
    app.button[-1].click().run()
    assert not app.exception
    comparison = app.dataframe[0].value
    assert comparison.columns[:2].tolist() == ["Scheduled", "Realtime-informed"]
    assert comparison.iloc[2, 0] > comparison.iloc[2, 1] > comparison.iloc[2, 2]
    assert any("Mean wait changes" in m.value for m in app.markdown)
    assert any("Incomplete timing coverage" in w.value for w in app.warning)

    monkeypatch.setattr(realtime_view, "time", lambda: epoch + 91)
    app.run()
    assert app.button[-1].disabled and not app.metric
    assert any("Stale" in w.value for w in app.warning)
    app.radio[1].set_value("Saved snapshot").run()
    app.file_uploader[0].upload("capture.json", snapshot.archive().encode(), "application/json").run()
    app.button[-1].click().run()
    assert not app.exception and app.metric
    app.date_input[0].set_value(day + timedelta(days=1)).run()
    assert app.button[-1].disabled and not app.metric
    app.file_uploader[0].set_value(("bad.json", b"{}", "application/json")).run()
    assert app.error and app.button[-1].disabled
