# SofiaLineHop

SofiaLineHop is an academic prototype for studying one transfer between two Sofia public transport lines. It combines a scheduled arrival, a walk between stops and a scheduled departure. The Streamlit app shows the walking route and compares the published timetable with hypothetical shifts to the outgoing service.

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

Run the full automated suite from the same environment with `python -m pytest`. Its fixtures supply local timetables and pedestrian graphs.

## Data and first launch

**Timetable.** Sofia’s Urban Mobility Centre publishes the scheduled routes, trips, stop visits and service dates. The demonstration uses static GTFS feed version 1.2 with `feed_start_date=20261126` and `feed_end_date=20271126`. Calendar entries determine which trips actually run on the selected day. [Sofia Municipality transport data](https://www.sofia.bg/en/transport-data)

**Walking network.** On first use OSMnx downloads the walkable network for “Sofia, Bulgaria” from OpenStreetMap, retains disconnected components and saves a GraphML file under `data/processed/pedestrian/`. **Finding connected stops…** can include this download or loading the saved file. Open the app before presenting to populate the cache. Subsequent route selections reuse the graph in memory. The Folium map also uses online tiles and browser assets. [© OpenStreetMap contributors](https://www.openstreetmap.org/copyright)

**For an exact replay**, copy both `data/raw/gtfs/` and `data/processed/pedestrian/` with their filenames to the demonstration machine. Git excludes the datasets. New downloads can change stops, paths and results. The reference GTFS ZIP has SHA-256 `A35C31BFBB2AC127CD80E586451839CE2D6A1B5E78DF804E25EB28823639BF06`. The reference GraphML has SHA-256 `E0122AE06337CB0C5CEBD16E8EDA36B68BB9642C29062D805BBF212521365A14` and contains 82,057 nodes and 222,118 directed edges. The demonstration used OSMnx 2.2.0, NetworkX 3.7 and Streamlit 1.67.0.

## Three demonstration scenarios

Use **26 November 2026**, **07:00–08:00**, **All directions** for both routes, a **500 m** maximum walking distance, **1.4 m/s** walking speed and a **30 s** boarding buffer. Set the outgoing departure delay to **0 s** and the shift slider to **−5 through +5 minutes**. Use the incoming delay in the table. Match the IDs in parentheses in the route and stop selectors, especially for the two lines numbered 1.

| Connection | Alight → board | Incoming delay | Walk | Completed / attempts, original → best | Mean wait, original → best | Best shift |
| --- | --- | ---: | ---: | --- | --- | ---: |
| Tram 18 (`TM34`) → metro M1 (`M1`) | Пл. Св. Неделя (`TM1307`) → Сердика (`M7`) | 0 s | 190 m | 4/5 → 4/5 | 2.51 → 1.51 min | −1 min |
| Trolleybus 1 (`TB10`) → tram 1 (`TM27`) | Бул. Ал. Стамболийски (`TB0283`) → Пл. Възраждане (`TM1269`) | 120 s | 476 m | 4/6 → 4/6 | 5.83 → 3.83 min | −2 min |
| Metro M4 (`M4`) → metro M2 (`M2`) | Сердика (`M7`) → Сердика II (`M208`) | 0 s | 128 m | 17/19 → 17/19 | 2.89 → 1.15 min | −2 min |

For the **tram 18** example, check the first arrival by hand. The tram arrives at 07:08:00. Walking 189.81 m at 1.4 m/s takes 135.58 s. With the buffer, the passenger is ready at 07:10:46 and can board the 07:13:20 departure. The transfer takes 320 s, including 184.42 s of waiting after walking.

For the **trolleybus** example, both columns include the two-minute arrival delay. Their difference isolates the effect of shifting the tram timetable. For the **metro interchange**, use the map to discuss what the 128 m represents. The model measures a path between snapped map nodes and omits the stairs, platforms and corridors a passenger may use underground.

## Architecture and network models

| Component | Responsibility |
| --- | --- |
| `src/gtfs_loader.py`, `src/models.py` | Validate GTFS tables and build a service-day schedule of stops, routes, trips and ordered stop visits. Preserve IDs as strings and store times in seconds from the service-day origin, including times beyond 24:00. |
| `src/pedestrian_network.py` | Load or build a directed NetworkX multigraph. Nodes have WGS84 coordinates and edges have lengths in metres. Snap stops to nearest nodes and find a shortest walking path by edge length. |
| `src/transfers.py` | For two distinct routes and optional directions, identify alighting and boarding stops, then search from each distinct origin node up to the distance limit. For a selected pair, extract its timed arrival and departure visits. |
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
| Missed intended connection rate | Fraction of attempts with a feasible scheduled departure whose intended vehicle actually left before the passenger was ready. Intention is computed after the scenario offset and before delays. An attempt may miss that vehicle and complete on a later one. |

Undefined statistics return `None`. The API reports seconds and fractions. The UI shows minutes and percentages. Interval summaries group by **scheduled** arrival in bins aligned to service-day midnight. The UI offers 15, 30 and 60 minutes. Pooled stochastic summaries give each attempt equal weight across repetitions.

## Schedule optimization

The app tests every whole-minute shift in the selected range (within ±15 minutes) and always evaluates zero. Negative offsets move the outgoing departures earlier. All offsets use the same incoming cohort, walking time, buffer and delay assumptions. Stochastic comparisons in the API share per-visit delay draws across offsets.

An offset must complete at least as many attempts as the original schedule to qualify. Among those offsets, the UI minimizes mean waiting time. Ties favor the smallest absolute change and then the earlier departure. If all eligible means are undefined, zero wins. The comparison table shows the winner and baseline, and the scenario table includes every evaluated offset.

The Python entry point `optimize_offsets` accepts integer-second bounds and steps. It can also minimize median wait, maximum wait, mean total duration or incomplete rate, or maximize successful rate. Shifts apply in memory to the selected outgoing connection.

## Known limitations

- Results describe scheduled stop visits. The model omits passenger counts, capacity, observed delays, traffic correlations and delay propagation along a trip.
- The walking estimate excludes stop-to-node access distances, accessibility constraints, GTFS station pathways and operator rules in `transfers.txt`. The buffer is a user assumption.
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

Fetching raises `RealtimeError` on network, decoding or freshness failures. Feed and trip freshness default to 90 seconds. Replay evaluates freshness at the original retrieval time. Supply `as_of=int(time.time())` when checking a saved snapshot for live use. Around midnight, also match the previous day's full schedule for trips with after-midnight stop times. Explicit trip dates take priority. For undated trips with absolute predictions the matcher selects the nearest service day by comparing predicted and scheduled visits. Without such predictions it uses the feed's Sofia calendar date.

The offline tests construct protobuf messages locally. [GTFS Realtime reference](https://gtfs.org/documentation/realtime/reference/)
