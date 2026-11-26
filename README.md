
# SofiaLineHop

Digital twin for public transport transfers in Sofia.

## Overview

SofiaLineHop is an urban digital twin prototype designed to model,
simulate and analyze public transport transfers in Sofia.

The system combines public transport schedules with the pedestrian
network to evaluate transfer efficiency and explore how changes
in transport schedules could improve connectivity between lines.

The project is intended as an academic proof of concept rather
than a production-ready transportation management system.

## Objectives

- Build a digital representation of public transport transfers.
- Estimate walking and waiting times between transport services.
- Simulate transfers under different conditions.
- Identify inefficient transfer connections.
- Evaluate alternative transport schedules.
- Visualize and compare simulation results.

## Features

- Import and process GTFS data.
- Construct a pedestrian network from OpenStreetMap.
- Identify possible transfers between transport lines.
- Calculate pedestrian routes and walking times.
- Simulate scheduled and delayed vehicle arrivals.
- Calculate transfer performance metrics.
- Evaluate alternative schedule offsets.
- Visualize stops, routes and simulation results.
- Compare baseline and alternative scenarios.

## Technology Stack

- Python
- Pandas
- NumPy
- OSMnx
- NetworkX
- Streamlit
- Folium
- Plotly
- Pytest

## Data Sources

- GTFS public transport schedules for Sofia.
- OpenStreetMap pedestrian infrastructure.

The prototype uses available datasets and does not require
field observations, physical sensors or real-time vehicle tracking.

## Architecture

The system is implemented as a modular Python application.

The main components are:

- Data ingestion and preprocessing.
- Public transport model.
- Pedestrian network model.
- Transfer identification.
- Transfer simulation.
- Statistical analysis.
- Schedule optimization.
- Interactive visualization.

## Project Structure

    .
    ├── data/
    │   ├── raw/
    │   └── processed/
    ├── src/
    │   ├── __init__.py
    │   ├── models.py
    │   ├── gtfs_loader.py
    │   ├── pedestrian_network.py
    │   ├── transfers.py
    │   ├── simulation.py
    │   ├── analytics.py
    │   └── optimization.py
    ├── tests/
    ├── app.py
    ├── requirements.txt
    ├── README.md
    ├── AGENTS.md
    └── .gitignore

## Getting Started

Create a virtual environment:

    python -m venv .venv

Activate the environment and install dependencies:

    pip install -r requirements.txt

Place the required GTFS dataset in:

    data/raw/gtfs/

Run the application:

    streamlit run app.py

Run the tests:

    python -m pytest

## Simulation

The simulation evaluates transfers between selected incoming
and outgoing public transport services.

A transfer is considered feasible when a passenger can reach
the outgoing service before its departure.

Simulation parameters may include:

- Selected transport lines and directions.
- Transfer stops.
- Date and time interval.
- Pedestrian walking speed.
- Minimum transfer buffer.
- Vehicle arrival and departure delays.
- Schedule offsets.

### Stochastic vehicle delays

For example, to simulate 100 possible timetables for a selected connection:

```python
from src.simulation import DelayModel, simulate_stochastic_transfers

runs = simulate_stochastic_transfers(
    schedule, connection, walking_route, parameters,
    arrival_delay=DelayModel(minimum_seconds=0, maximum_seconds=120),
    departure_delay=DelayModel(minimum_seconds=0, maximum_seconds=60),
    repetitions=100, seed=42,
)
```

These distributions are hypothetical scenario assumptions. They have not been
fitted to or validated against observed Sofia vehicle delays. Each whole-second
delay between the specified bounds is equally likely, including both endpoints.
Equal bounds give a fixed delay. The default bounds are both zero. Any fixed
arrival or departure delay in `SimulationParameters` is added to the draw.
Vehicles can run late or on time. Each stop visit has an independent draw,
including repeat visits of the same trip. Each repetition generates a new
timetable shared by all passengers. This omits correlations due to traffic,
time of day, or delay propagation. A seed replays the same sequence for the
same inputs and software version.

The outer list indexes repetitions. Each inner list follows scheduled arrival
order. Only visits scheduled in the half-open simulation window enter the
scenario. Every selected arrival counts as an attempt, even if delayed beyond
the horizon. Passengers board the earliest actual departure they can reach
with the walking time and buffer, strictly before the end of the window.

For each attempt, `transfer.successful` reports completion within the horizon.
`intended_departure` is the first feasible departure on the original timetable.
`missed_intended_connection` is true if that vehicle actually departed before
the passenger was ready, and is `None` if there was no scheduled connection.
A passenger can miss the intended vehicle and still board a later one. Conversely,
a ready passenger whose vehicle departs beyond the horizon has an incomplete
transfer without having missed the vehicle. Waiting and total duration use
actual times, while the scheduled times in `transfer` identify the timetable
events used.

## Performance Metrics

- Mean waiting time.
- Median waiting time.
- Maximum waiting time.
- Total transfer duration.
- Successful transfer rate.
- Missed transfer rate.

## Optimization

The system evaluates alternative scenarios by applying
configurable time offsets to transport schedules.

Each scenario is simulated and compared against the original
schedule using selected performance metrics.

Optimization is limited to selected transfer connections,
rather than the entire public transport network.

## Limitations

- Accuracy depends on the quality of the available data.
- Vehicle movement is modeled rather than tracked in real time.
- Passenger demand and vehicle capacity are not modeled.
- Walking times and delays are based on configurable assumptions.
- Optimization results represent hypothetical scenarios, not
  operational recommendations for immediate implementation.

## Project Status

Academic prototype under development.
