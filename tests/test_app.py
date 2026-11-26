"""Exercise the Streamlit workflow offline with a small service-day timetable."""

import networkx as nx
from streamlit.testing.v1 import AppTest

from src import gtfs_loader, pedestrian_network
from src.models import Route, Schedule, Stop, StopTime, Trip


def test_transfer_workflow(monkeypatch):
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

    app = AppTest.from_file("../app.py", default_timeout=30).run()
    assert not app.exception
    assert app.selectbox[-1].options == ["Alight (a) → Board (b)"]
    assert "L.polyline" in app.get("iframe")[0].proto.srcdoc
    app.button[0].click().run()
    assert [metric.value for metric in app.metric[:2]] == ["1", "100.0%"]
    app.number_input[3].set_value(300).run()
    assert not app.metric
    app.button[0].click().run()
    assert app.metric[1].value == "0.0%"
