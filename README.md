# SofiaLineHop

SofiaLineHop studies a transfer between two Sofia public transport lines. GTFS Static defines the service and passenger cohort. OpenStreetMap supplies the walking path. GTFS Realtime Trip Updates supply predictions and service changes for matched visits. The Streamlit app compares the published timetable, conditions at capture and hypothetical shifts to the outgoing service.

## Install and run

Run the commands from the directory containing `app.py`. The demonstration was tested on Windows with Python 3.13.7.

1. Create a virtual environment and install the dependencies. In PowerShell:

   ```powershell
   py -3.13 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

   On macOS or Linux, use `python3.13 -m venv .venv` and `source .venv/bin/activate` before the same install command.

2. Put the unpacked timetable directly in `data/raw/gtfs/`. For example, `data/raw/gtfs/stops.txt` must exist. The loader reads `stops.txt`, `routes.txt`, `trips.txt` and `stop_times.txt`, plus at least one of `calendar.txt` and `calendar_dates.txt`. Use files from one release. The app reads them locally. [Download Sofia Traffic’s static GTFS ZIP](https://gtfs.sofiatraffic.bg/api/v1/static)

3. Start the local server and open the local URL printed in the terminal. Leave it running throughout the demonstration and press Ctrl+C to stop it.

   ```sh
   python -m streamlit run app.py --server.address localhost --server.headless true
   ```

4. Choose a **Service date** covered by the feed, two routes and a transfer stop pair. Expand **Simulation parameters**, set the outgoing shift range and click **Run simulation**. After changing a setting, click the button again. The results include the route map, original and optimized metrics, a wait histogram, interval comparisons and a table of all evaluated shifts.

   For a snapshot experiment, select **Realtime-informed**. Fetch Trip Updates from the live feed or upload a saved snapshot JSON. **Save snapshot** downloads a live capture for later replay. The app automatically selects a compatible service date and interval when needed. You can narrow the interval within the snapshot forecast window. The results compare scheduled, realtime-informed and optimized KPIs under the same hypothetical delays. The recommendation reports the outgoing shift, mean wait and completion rate for the selected connection.

Run the full automated suite from the same environment with `python -m pytest`. Its fixtures supply local timetables and pedestrian graphs.

## Data and first launch

**Timetable.** Sofia’s Urban Mobility Centre publishes the scheduled routes, trips, stop visits and service dates. The demonstration uses static GTFS feed version 1.2 with `feed_start_date=20261126` and `feed_end_date=20271126`. Calendar entries determine which trips actually run on the selected day. [Sofia Municipality transport data](https://www.sofia.bg/en/transport-data)

**Spatial cache.** On the first transfer search, the app builds `data/processed/sofia_transport.gpkg` from the validated GTFS stops and the local Sofia GraphML file under `data/processed/pedestrian/`. If neither a usable GeoPackage nor a local graph is available, OSMnx downloads the Sofia walking graph, including disconnected components. Later sessions reload stops and the directed graph from the GeoPackage. The Folium map uses online tiles and browser assets. [? OpenStreetMap contributors](https://www.openstreetmap.org/copyright)

**For an exact replay**, copy `data/raw/gtfs/` and `data/processed/sofia_transport.gpkg` to the demonstration machine. An existing `data/processed/pedestrian/` GraphML cache can also bootstrap the package offline. Git excludes the datasets. The reference GTFS ZIP has SHA-256 `A35C31BFBB2AC127CD80E586451839CE2D6A1B5E78DF804E25EB28823639BF06`. The reference GraphML has SHA-256 `E0122AE06337CB0C5CEBD16E8EDA36B68BB9642C29062D805BBF212521365A14` and contains 82,057 nodes and 222,118 directed edges. The demonstration used OSMnx 2.2.0, NetworkX 3.7 and Streamlit 1.67.0.

## Reproduce the three-source experiments

After installing the dependencies, run these commands from the repository root. The ZIP contains the original static tables used by the experiment, the original Trip Updates capture in the app's JSON archive format, and a central Sofia GraphML extract. The replay works offline and leaves the app's own datasets in place.

```sh
python -m zipfile -e demos/sofia-20261127.zip data/processed/demo-20261127
python -m demos.replay
```

**Frozen inputs.** The ZIP SHA-256 is `2c605d94925e09c8ac448d7b788053d9057632a5445a565e6da2734e89529566`. Sofia Traffic published the snapshot on 27 November 2026 at 12:02:46 Europe/Sofia. Retrieval followed at 12:02:47. The raw protobuf SHA-256 is `3358495286e461ac2b539714bffc8a52e76fbad59d8fb434dd4bfc51d5a6195b`. The map extract retains 2,343 nodes and 6,348 edges from the cached city graph. Its extent is 23.304–23.327° E and 42.691–42.704° N. Both graph sizes produced identical walk lengths and displayed results for the two selected pairs. The run used gtfs-realtime-bindings 3.0.0, protobuf 7.36.2 and NumPy 2.5.5.

**Data credits.** The timetable and Trip Updates are from Sofia Municipality and the Urban Mobility Centre. The bundle selects static tables and preserves the captured protobuf. The walking graph extract derives from © OpenStreetMap contributors and is available under the Open Database License. [Sofia data and CC BY 4.0 terms](https://www.sofia.bg/en/transport-data) · [OpenStreetMap data and ODbL terms](https://www.openstreetmap.org/copyright)

**Shared controls.** Use 27 November 2026, 12:03–13:00 Sofia time, all directions, 500 m path limit, 100 m snap limit, 1.4 m/s walk, 30 s boarding buffer and zero added outgoing delay. Each comparison uses the same five incoming visits on its selected connection. Each offset search evaluates −300 through +300 s in 60 s steps. Fixed delays and a single repetition make these runs deterministic.

| Experiment | Controlled comparison | Completed | Mean wait after walking | Missed intended departures |
| --- | --- | --- | --- | --- |
| 1. Timetable versus forecast | Tram 18 to metro M1, `TM1307` to `M7`, 189.81 m walk. Replace published times with the snapshot, with zero added delays and shift. | 4/5 in both | 180.67 → 219.92 s | 0/4 in both |
| 2. Incoming delay | Trolleybus 1 to tram 1, `TB0283` to `TM1269`, 476.22 m walk. Keep the snapshot and zero shift. Add 120 s to each incoming arrival. | 4/5 in both | 319.85 → 379.85 s | 0/4 → 1/4 |
| 3. What-if schedule optimization | Keep experiment 2's snapshot and 120 s disturbance. Compare zero shift with the winning tram departure shift of **240 s later**. | 4/5 in both | 379.85 → 259.85 s | 1/4 → 0/4 |

In experiment 1, the feed predicted the scheduled 12:10 tram arrival 157 s early. Three of the five arrivals had reported times. The other two arrivals and all candidate metro departures used the timetable. In experiment 2, all five arrival times were reported. The extra 120 s is a hypothetical disturbance. One passenger missed the intended departure but could still board within the window. In experiment 3, the optimizer selected the shift by mean wait subject to completion. The intended miss rate is a separate outcome.

**Replay in Streamlit.** Use the city graph and matching static release described above. Select **Realtime-informed**, **Saved snapshot**, and upload the extracted `1795773766.json`. Set the shared controls, then select `TM34` / `M1` for experiment 1 or `TB10` / `TM27` for experiments 2 and 3. Select the stop IDs in the table. Click **Run simulation** after each delay change. Compare the scheduled and realtime columns for experiment 1, the zero-offset realtime rows across runs for experiment 2, and the zero and winning offsets in the delayed run for experiment 3.

**Validation.** The full test suite passed 117 tests under Python 3.13.7. A separate Streamlit AppTest run uploaded the real archive, selected both connections against the city graph and reproduced the CLI mean waits and completion rates. It checked the result table, map component and both charts. Browser tile rendering and actual walking times were outside that check.

**Coverage and freshness.** Of 1,327 captured entities, 1,323 matched the day's 16,262 trips. Three had no matching active trip and one measurement was 93 s old. Across 758,330 arrival/departure slots, 49,866 times were reported, 3,340 inferred and 705,124 used the timetable. These counts cover the full service day. A single capture cannot establish forecast accuracy, actual passenger outcomes or the provider's update cadence.

The app reads static files after local replacement and caches schedules by service date and file modification times. To fetch current map data, set `osmnx.settings.use_cache = False` in the rebuild process, call `build_pedestrian_network(refresh=True)`, then rerun the app. The changed GraphML file invalidates the processed graph and its derived searches and walks. A rebuild with the default settings can reuse OSMnx's HTTP cache. The cached Overpass response records an OSM base timestamp of 26 November 2026 at 18:45:27 UTC. The city graph was built that day. Its creation date does not establish the survey date of any edge. Live Trip Updates refresh on button press. Each app rerun checks freshness. An idle browser has no polling timer. The 90 s threshold and one-hour forecast horizon are application settings, independent of publisher cadence. [Sofia Trip Updates endpoint](https://gtfs.sofiatraffic.bg/api/v1/trip-updates)

## Scheduled-only demonstration scenarios

Use **26 November 2026**, **07:00–08:00**, **All directions** for both routes, a **500 m** maximum walking distance, **1.4 m/s** walking speed and a **30 s** boarding buffer. Set the outgoing departure delay to **0 s** and the shift slider to **−5 through +5 minutes**. Use the incoming delay in the table. Match the IDs in parentheses in the route and stop selectors, especially for the two lines numbered 1.

| Connection | Alight → board | Incoming delay | Walk | Completed / attempts, original → best | Mean wait, original → best | Best shift |
| --- | --- | ---: | ---: | --- | --- | ---: |
| Tram 18 (`TM34`) → metro M1 (`M1`) | Пл. Св. Неделя (`TM1307`) → Сердика (`M7`) | 0 s | 190 m | 4/5 → 4/5 | 2.51 → 1.51 min | −1 min |
| Trolleybus 1 (`TB10`) → tram 1 (`TM27`) | Бул. Ал. Стамболийски (`TB0283`) → Пл. Възраждане (`TM1269`) | 120 s | 476 m | 4/6 → 4/6 | 5.83 → 3.83 min | −2 min |
| Metro M4 (`M4`) → metro M2 (`M2`) | Сердика (`M7`) → Сердика II (`M208`) | 0 s | 128 m | 17/19 → 17/19 | 2.89 → 1.15 min | −2 min |

For the **tram 18** example, check the first arrival by hand. The tram arrives at 07:08:00. Walking 189.81 m at 1.4 m/s takes 135.58 s. With the buffer, the passenger is ready at 07:10:46 and can board the 07:13:20 departure. The transfer takes 320 s, including 184.42 s of waiting after walking.

For the **trolleybus** example, both columns include the two-minute arrival delay. Their difference isolates the effect of shifting the tram timetable. For the **metro interchange**, use the map to discuss what the 128 m represents. The model measures a path between snapped map nodes and omits the stairs, platforms and corridors a passenger may use underground.

## GeoPackage storage

GeoPackage is an Open Geospatial Consortium (OGC) encoding standard for storing spatial layers and other data in a portable SQLite file. SofiaLineHop uses GeoPandas with GDAL via Pyogrio to persist processed spatial data in `sofia_transport.gpkg` and to exchange selected transfers with desktop GIS tools. [OGC GeoPackage Encoding Standard](https://www.ogc.org/standards/geopackage/)

Choose **Download GeoPackage** below the map to save the selected stops and walking transfer. In QGIS, expand the downloaded file in the Browser panel and add either layer independently. Open the `transfer_paths` attribute table to inspect the route and stop IDs, service date, walking speed, distance and duration. [QGIS Browser panel](https://docs.qgis.org/3.44/en/docs/user_manual/introduction/browser.html)

For a snapshot that also includes the routable pedestrian graph, use the Python API with an existing schedule, connection and calculated walk.

```python
from src.geopackage import StoredTransfer, read_geopackage, write_geopackage

path = "data/processed/transfers.gpkg"
record = StoredTransfer(connection, walk, schedule.service_date, walking_speed_mps)
write_geopackage(path, schedule.stops.values(), [record], network=graph)
snapshot = read_geopackage(path)
origin = snapshot.stops[record.connection.incoming.stop_id]
restored_walk = snapshot.transfers[0].walk
restored_graph = snapshot.network
```

| Layer | Geometry and CRS | Attributes and interpretation |
| --- | --- | --- |
| `stops` | Point, EPSG:4326 | GTFS `stop_id` and `stop_name` as text. Coordinates are published longitude and latitude. |
| `transfer_paths` | Nullable LineString, EPSG:4326 | `from_stop_id`, `to_stop_id`, `from_route_id` and `to_route_id` are GTFS text IDs. Optional fields are integer direction IDs, ISO `service_date`, numeric `walking_speed_mps`, `distance_m` and `duration_s`, ordered `node_ids` as JSON, and `single_vertex` as JSON for a one-vertex walk. |
| `pedestrian_nodes` | Point, source graph CRS | Integer `node_id`, including isolated nodes. Node tags are in the `attrs` JSON field. Graph attributes are layer metadata. |
| `pedestrian_edges` | LineString, source graph CRS | Directed multigraph key `(u, v, edge_key)`, original `length_m` and JSON attributes. Edges without a supplied shape display as endpoint segments. The `has_shape` flag lets the reader restore the original edge attributes. |

Pass `StoredTransfer(connection)` to save a connection before calculating its walk. A calculated walk between stops snapped to the same node retains its node ID, single vertex and zero cost even though its line geometry is null. Walking distances exclude off-network access to the stops.

Each write replaces the entire destination file once all layers have been written. Omit `network` for a compact transfer-only package. The network API accepts SofiaLineHop’s OSMnx directed multigraph with integer IDs and keys, node `x`/`y`, edge `length` and JSON-compatible graph tags. The app manages `sofia_transport.gpkg` automatically. Use a different filename for manual exports.

The managed package records a schema version and source file sizes and modification times. Changing `stops.txt` refreshes the stops and derived results. Replacing GraphML refreshes the network. Search results include empty matches and are keyed by GTFS file versions, service date, routes, directions, walking limit and snap limit. Walks are keyed by date, connection, walking speed and snap limit within that spatial dataset. The app serializes cache writes and publishes a rebuilt package only after all layers and metadata are ready.

A missing, unreadable or incompatible package is rebuilt from available local inputs. A valid package can supply stops and the graph even if `stops.txt` or GraphML is absent. Other GTFS timetable tables remain necessary for service-day schedules, simulation and optimization. Rebuilds require readable sources for the affected data. Source detection uses file metadata; after replacing inputs while preserving both size and timestamp, touch the changed file to trigger invalidation.

### GeoPackage validation

Run `python -m pytest` to check the layer registry, SQLite integrity, CRS, geometry and attributes, graph reconstruction, and independent reads of the Streamlit download layers. For format conformance, run `gdal driver gpkg validate --full-check <file.gpkg>` with GDAL 3.13+ and its Python bindings, or use the official `validate_gpkg.py -v -k --extra --warning-as-error <file.gpkg>` sample script. The validator checks the file format. The application tests check routing and transfer semantics. [GDAL GeoPackage validator](https://gdal.org/en/stable/programs/gdal_driver_gpkg_validate.html) · [GDAL sample validators](https://gdal.org/en/stable/api/python/python_samples.html)

## Architecture and network models

| Component | Responsibility |
| --- | --- |
| `src/gtfs_loader.py`, `src/models.py` | Validate GTFS tables and build a service-day schedule of stops, routes, trips and ordered stop visits. Preserve IDs as strings and store times in seconds from the service-day origin, including times beyond 24:00. |
| `src/pedestrian_network.py` | Load or build a directed NetworkX multigraph. Nodes have WGS84 coordinates and edges have lengths in metres. Snap stops to nearest nodes and find a shortest walking path by edge length. |
| `src/geopackage.py`, `src/spatial_cache.py` | Write and read spatial feature layers, reconstruct the pedestrian graph, and reuse cached stops, searches and walks across app sessions. |
| `src/transfers.py` | For two distinct routes and optional directions, identify alighting and boarding stops, then search from each distinct origin node up to the distance limit. For a selected pair, extract its timed arrival and departure visits. |
| `src/gtfs_realtime.py`, `src/realtime_schedule.py` | Fetch or replay a full snapshot, match dated trips and stop visits, overlay event times and service relationships on the static schedule, and track provenance and coverage. |
| `src/realtime_view.py` | Select live or archived input, check freshness, align the service window and display integration diagnostics. |
| `src/simulation.py` | Match scheduled or delayed arrivals to feasible departures and record individual outcomes. |
| `src/analytics.py`, `src/optimization.py` | Summarize outcomes, evaluate local timetable offsets and select the best eligible scenario. |
| `app.py`, `src/results_view.py` | Collect inputs, cache timetables and routes, render the Folium map and display results with pandas and Plotly. |

The timetable applies weekly service calendars and date exceptions. The first visit of a trip cannot supply an alighting passenger and the last cannot supply a boarding. Explicit GTFS pickup/drop-off prohibitions are respected. Untimed intermediate visits can identify possible locations but cannot generate simulation events. Each timed repeat visit is a separate event.

The UI accepts a snap distance of at most 100 m per stop. The walking limit applies to the directed network path between snapped nodes. Two stops can share a node and yield zero walking time. A connection can exist geographically even when no timed transfer is available in the selected interval.

## Simulation and statistical assumptions

Each scheduled incoming visit in the half-open interval `[start, end)` contributes one equally weighted attempt. A window crossing midnight continues on the selected GTFS service day. For each offset, the simulation selects departures whose **shifted scheduled times** fall inside the window. A shift can therefore bring a departure into view. An incoming delay can push an attempt beyond the horizon and it still counts.

Walking time is distance divided by the selected constant speed. Boarding requires an actual departure **at or after** actual arrival plus walking time rounded up to whole seconds plus the buffer. The model chooses the earliest eligible actual departure strictly before the end of the window. Equality at the boarding threshold succeeds. Duration and waiting calculations use the unrounded walk.

The UI applies fixed nonnegative delays once per visit and runs one timetable per offset. The Python API also supports repeated timetables with independent discrete-uniform delays per visit. Bounds are inclusive whole seconds and fixed delays are added to each draw. Every arrival in one repetition sees the same set of realized departures. Delay distributions are hypothetical. A seed reproduces a run with the same inputs and software.

```python
from itertools import chain
from src.analytics import summarize_transfers
from src.simulation import DelayModel, simulate_stochastic_transfers

# Use the schedule, connection, walking route and parameters for the selected pair.
runs = simulate_stochastic_transfers(
    schedule, connection, walking_route, parameters,
    arrival_delay=DelayModel(0, 120), departure_delay=DelayModel(0, 60),
    repetitions=100, seed=42,
)
metrics = summarize_transfers(chain.from_iterable(runs))
```

## Performance metrics

| Metric | Calculation and interpretation |
| --- | --- |
| Waiting time | Actual boarded departure minus actual arrival minus walking time. Includes the boarding buffer. Mean, median and maximum use completed attempts only. |
| Waiting time variability | Population standard deviation of completed waits. P50, P90 and P95 use linear interpolation at rank `(n − 1) × p / 100` in the sorted waits. |
| Mean total transfer duration | Mean elapsed time from actual arrival to actual boarded departure, over completions. |
| Successful and incomplete rates | Completed and uncompleted attempts, respectively, divided by all attempts. The API also calls the incomplete rate `missed_rate`. |
| Missed intended connection rate | Among attempts with a modeled arrival and a feasible intended departure on the offset timetable, the fraction whose intended visit was suppressed or left before the passenger was ready. A later boarding can still complete the transfer. An intended vehicle delayed beyond the horizon counts as catchable if the passenger would be ready. |

Undefined statistics return `None`. The API reports seconds and fractions. The UI shows minutes and percentages. Interval summaries group by **scheduled** arrival in bins aligned to service-day midnight. The UI offers 15, 30 and 60 minutes. Pooled stochastic summaries give each attempt equal weight across repetitions.

## Schedule optimization

The app tests every whole-minute shift in the selected range (within ±15 minutes) and always evaluates zero. Negative offsets move the outgoing departures earlier. All offsets use the same incoming cohort, walking time, buffer and delay assumptions. Stochastic comparisons in the API share per-visit delay draws across offsets.

An offset must complete at least as many attempts as the original schedule to qualify. Among those offsets, the UI minimizes mean waiting time. Ties favor the smallest absolute change and then the earlier departure. If all eligible means are undefined, zero wins. The comparison table shows the winner and baseline, and the scenario table includes every evaluated offset.

The Python entry point `optimize_offsets` accepts integer-second bounds and steps. It can also minimize median wait, maximum wait, mean total duration or incomplete rate, or maximize successful rate. Shifts apply in memory to the selected outgoing connection.

## Known limitations

- Results describe modeled stop visits. Realtime predictions can propagate along a trip. The model omits passenger counts, capacity, traffic correlations and independent verification of vehicle movements.
- The walking estimate excludes stop-to-node access distances, accessibility constraints, GTFS station pathways and operator rules in `transfers.txt`. The buffer is a user assumption. The prototype treats conditional pickup and drop-off as available. It does not route to reassigned platforms or apply realtime stop-property overrides. The capture contained no such overrides.
- **All directions** pools visits on the selected line at the chosen stop. Where the feed omits direction IDs, the app cannot distinguish directions. A traveler with a particular destination may have fewer boarding options.
- The end of the observation window affects completion rates. A passenger who could board just after the horizon counts as incomplete. Waiting-time summaries omit such passengers.
- The search evaluates one connection over one time window. It does not model downstream transfers, fleet circulation or network-wide feasibility. The measured improvements are hypothetical.

## GTFS Realtime Trip Updates

The Python adapter reads Sofia's GTFS Realtime 2.0 full snapshots. Save one alongside the corresponding static timetable to replay an experiment offline. Use the full service-day schedule so repeated stops can be identified reliably.

```python
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.gtfs_loader import load_schedule
from src.gtfs_realtime import Snapshot, fetch_snapshot, match_updates

snapshot = fetch_snapshot()
path = Path("data/raw/realtime") / f"{snapshot.source_timestamp}.json"
snapshot.save(path)

replay = Snapshot.load(path)
day = datetime.fromtimestamp(replay.source_timestamp, ZoneInfo("Europe/Sofia")).date()
schedule = load_schedule(Path("data/raw/gtfs"), day)
trips, issues = match_updates(replay, schedule)
```

The archive contains the original protobuf bytes and the retrieval timestamp. Matching returns explicit updates by static trip ID and diagnostics for rejected records. Each reported visit carries its static stop sequence, relationship, and separate arrival and departure predictions. Event timestamps are Unix seconds. Signed delays use the scheduled event where available. When both time and delay are reported, the absolute time takes precedence and the reported delay is retained separately. Omitted stops have no explicit prediction in this adapter.

If both feeds declare a static feed version, mismatched versions block integration. This capture omitted the optional realtime header version. Its compatibility evidence comes from the service calendar, trip and visit matches. When a trip ID is absent, matching requires a unique route, direction, service date and start time, stop IDs and absolute predictions for reported timings. Unknown trips, unsupported trip relationships and ambiguous visits generate diagnostics. The model cannot infer the path of an added or rerouted service. Realtime links to OSM through the matched static stop coordinates. No vehicle position feed is required.

Fetching raises `RealtimeError` on network, decoding or freshness failures. Feed and trip freshness default to 90 seconds. Replay evaluates freshness at the original retrieval time. Supply `as_of=int(time.time())` when checking a saved snapshot for live use. Around midnight, also match the previous day's full schedule for trips with after-midnight stop times. Explicit trip dates take priority. For undated trips with absolute predictions the matcher selects the nearest service day by comparing predicted and scheduled visits. For an undated update without absolute predictions, the matcher compares the measurement time with adjacent service-day operating intervals, accounting for a reported trip delay. Ties remain unresolved. GTFS service-day seconds start twelve elapsed hours before local noon in Europe/Sofia, including on clock-change days.

The offline tests construct protobuf messages locally. [GTFS Realtime reference](https://gtfs.org/documentation/realtime/reference/)

### Compare scheduled and updated visits

Pass the full service-day schedule and a snapshot to the model API. The view keeps a read-only baseline, the feed and retrieval timestamps, matched trip updates and any matching diagnostics.

```python
from src.realtime_schedule import integrate_schedule

view = integrate_schedule(schedule, replay)
coverage = view.coverage()            # Entire selected service day
tram_coverage = view.coverage("TM34")  # Same calculation for one static route
for trip in view.trips.values():
    for visit in trip.visits:
        arrival = visit.arrival
        # scheduled_seconds, updated_seconds and effective_seconds use the same service-day origin.
        if arrival.source == "reported":
            print(trip.scheduled.trip_id, visit.scheduled.stop_sequence, arrival.delay_seconds)
```

Each arrival and departure has a source. A `reported` time comes from the stop event. A `trip_delay` or `propagated` time uses a signed deviation applied to that event's own scheduled time. Trip delay applies before the first stop update. At a timed update, the arrival delay can carry forward to departure and the last known deviation carries to following stops. A departure-only update supplies no arrival prediction at its own stop. A skipped visit is suppressed while the preceding delay continues downstream. A `NO_DATA` update clears propagation until a new timed update. Canceled or deleted trips suppress every visit. [GTFS Realtime reference](https://gtfs.org/documentation/realtime/reference/)

With `scheduled_fallback`, only `effective_seconds` and `scheduled_seconds` have values. Both the prediction and delay are unknown. An untimed event without a prediction is `unavailable`. A `suppressed` event has no effective time. The original scheduled time remains available for comparison wherever the static feed supplies one.

Trip coverage divides trips with a matched update, including cancellations, by all selected static trips. Timing coverage divides reported and inferred predictions by all arrival and departure slots in those trips **and** trips without updates. The counts distinguish reported, propagated (including trip delays), fallback, unavailable and suppressed events. An empty denominator returns `None`. These fractions describe a snapshot against the full service day, including trips outside the snapshot's prediction horizon.

### Simulate and optimize a connection from a snapshot

Pass a full `RealtimeSchedule` from `integrate_schedule` wherever the simulation or optimization API takes a schedule. Use its `baseline` for the published timetable. The following example uses an existing selected connection, walk, and compatible simulation window.

```python
from src.simulation import simulate_transfers, simulate_stochastic_transfers, DelayModel
from src.optimization import optimize_offsets
from src.analytics import summarize_transfers

published = simulate_transfers(view.baseline, connection, walk, parameters)
forecast = simulate_transfers(view, connection, walk, parameters)
published_metrics, forecast_metrics = map(summarize_transfers, (published, forecast))

result = optimize_offsets(view, connection, walk, parameters,
                          min_offset_seconds=-120, max_offset_seconds=120, step_seconds=15)
if result.recommendation:
    print(result.recommendation.action, result.recommendation.baseline.mean_waiting_seconds,
          result.recommendation.proposed.mean_waiting_seconds)
print(result.arrival_sources, result.departure_sources)

runs = simulate_stochastic_transfers(view, connection, walk, parameters,
                                     arrival_delay=DelayModel(0, 30), repetitions=100, seed=42)
```

Use zero fixed delays with the published deterministic entry point. For fixed or random what-if delays on the published timetable, use `simulate_stochastic_transfers(view.baseline, ...)`. One repetition with zero draw bounds gives a deterministic scenario. A forecast outcome identifies the published incoming visit, intended and boarded visits, timing sources, and modeled arrival and departure in service-day seconds.

- **Timing.** Start from the integrated event time or its labeled timetable fallback. Add the outgoing schedule offset once to departures. Add any fixed hypothetical delay and one sampled extra delay once per visit. A realtime deviation is already included in the integrated time. The random and fixed delay inputs describe additional disturbances. Holding a prediction's deviation constant under a shift is a local what-if assumption.
- **Window.** Use a half-open interval on the selected service date. For snapshot experiments the entire interval must fit between 90 seconds before and one hour after the feed timestamp. This is the prototype's forecast horizon. Comparisons use epoch time derived from the Sofia GTFS service-day origin, including visits after 24:00. Archived snapshots replay against their original timestamp.
- **Attempts.** Each timed, alightable *published* incoming visit in the window supplies one attempt across all conditions and offsets. A canceled, deleted or skipped incoming visit counts as incomplete with no modeled arrival or assessable intended-connection miss. Suppressed departures cannot be boarded. An available passenger can miss a suppressed intended departure and still complete the transfer on a later one. Missing timing information uses the labeled scheduled fallback.
- **Boarding.** Published intentions use the offset timetable and scheduled passenger arrival. Candidate departures use the shifted base time for the chosen condition, so an early or late prediction can move a departure into or out of the window. A candidate delayed beyond the end by additional disturbances cannot be boarded. The earliest feasible modeled departure wins. Static visits without the relevant published time are outside the comparable event pool.
- **Comparison and recommendation.** Realtime optimization returns the published zero-offset reference and realtime zero-offset and shifted scenarios with the same incoming cohort, candidate pool and paired random draws. The published reference uses the same hypothetical delay settings. Source counts cover incoming attempts and distinct outgoing candidates for zero or the winning offset, before repetitions. Recommendations specify the outgoing route, stop, shift direction and seconds, service window, criterion, and before/after metrics. They require local realtime evidence and a defined objective. All-fallback scenarios still produce metrics. A winning shift applies only to the selected connection under the modeled conditions.
