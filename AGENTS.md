
# TransferTwin

Digital twin for public transport transfers in Sofia.

## Overview

TransferTwin is an urban digital twin prototype designed to model,
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
