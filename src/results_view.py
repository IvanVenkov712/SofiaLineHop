"""Streamlit views of one local offset search and its transfer attempts."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .analytics import summarize_transfers_by_interval


def _minutes(seconds):
    return None if seconds is None else seconds / 60


def _percent(rate):
    return None if rate is None else rate * 100


def _metric_row(metrics):
    return {
        "Completed (%)": _percent(metrics.successful_rate),
        "Incomplete (%)": _percent(metrics.missed_rate),
        "Mean wait (min)": _minutes(metrics.mean_waiting_seconds),
        "Median wait (min)": _minutes(metrics.median_waiting_seconds),
        "Maximum wait (min)": _minutes(metrics.maximum_waiting_seconds),
        "Mean transfer duration (min)": _minutes(metrics.mean_total_duration_seconds),
        "Missed intended connection (%)": _percent(metrics.missed_connection_rate),
        "Wait standard deviation (min)": _minutes(metrics.waiting_std_seconds),
        **{f"P{p:g} wait (min)": _minutes(v) for p, v in metrics.waiting_percentiles_seconds.items()},
    }


def show_results(optimization, outcomes_by_offset, parameters):
    best = optimization.best_offset_seconds
    scenarios = optimization.scenarios
    original = scenarios[0]
    st.subheader("Simulation results")
    count, rate, wait = st.columns(3)
    attempts = len(outcomes_by_offset[0])
    count.metric("Original arrival attempts", attempts)
    if not attempts:
        st.info("No scheduled arrivals at the selected stop in this interval.")
    else:
        rate.metric("Original completed transfers", f"{original.successful_rate:.1%}")
        mean = _minutes(original.mean_waiting_seconds)
        wait.metric("Original mean wait", "—" if mean is None else f"{mean:.2f} min")

    st.subheader("Original and optimized schedules")
    labels = {0: "Original"}
    if best:
        labels[best] = f"Optimized ({best / 60:+g} min)"
    else:
        labels[0] = "Original and optimized (0 min)"
    st.caption("The search minimizes mean wait while preserving or improving the original completion rate. "
               "Ties favor the smallest shift, then the earlier departure. If no mean wait is defined, "
               "the search retains the original schedule.")
    comparison = pd.DataFrame({name: _metric_row(scenarios[offset]) for offset, name in labels.items()})
    st.dataframe(comparison, width="stretch")

    if attempts:
        st.subheader("Waiting time distribution")
        histogram = go.Figure()
        for offset, name in labels.items():
            waits = [_minutes(o.transfer.waiting_seconds) for o in outcomes_by_offset[offset]
                     if o.transfer.successful]
            histogram.add_histogram(x=waits, name=name, bingroup="wait", opacity=0.7)
        if any(len(trace.x) for trace in histogram.data):
            histogram.update_layout(barmode="overlay", xaxis_title="Wait after walking (min)",
                                    yaxis_title="Completed transfers")
            st.plotly_chart(histogram)
        else:
            st.info("No completed transfers in either schedule.")

        st.subheader("Performance by scheduled arrival time")
        left, right = st.columns(2)
        minutes = left.selectbox("Interval length (min)", [15, 30, 60], index=1)
        metric = right.selectbox("Interval metric", ["Mean wait (min)", "Completed (%)"])
        step = minutes * 60
        start = parameters.start_seconds
        bins = range(start - start % step, parameters.end_seconds, step)
        times = [f"{t // 3600:02d}:{t // 60 % 60:02d}" for t in bins]
        figure = go.Figure()
        for offset, name in labels.items():
            grouped = summarize_transfers_by_interval(outcomes_by_offset[offset], step)
            if metric == "Mean wait (min)":
                series = {t: _minutes(m.mean_waiting_seconds) for t, m in grouped.items()}
            else:
                series = {t: _percent(m.successful_rate) for t, m in grouped.items()}
            values = [series.get(t) for t in bins]
            figure.add_bar(x=times, y=values, name=name)
        figure.update_layout(barmode="group", xaxis_type="category", yaxis_title=metric,
                             xaxis_title="Interval start (GTFS service-day time)")
        st.plotly_chart(figure)

    st.subheader("All evaluated scenarios")
    rows = [{"Outgoing shift (min)": offset / 60, "Schedule": labels.get(offset, "Alternative"),
             **_metric_row(metrics)} for offset, metrics in scenarios.items()]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("Negative shifts depart earlier. Empty values indicate an undefined statistic.")
    st.subheader("Assumptions and limitations")
    st.write("Each scheduled incoming arrival counts as one attempt. Walking uses the mapped pedestrian "
             "route at the selected constant speed. Each vehicle receives its configured fixed delay. "
             "Boarding requires enough time to walk and meet the buffer before an in-window departure.")
    st.write("Wait and duration cover completed transfers only. Wait starts after walking and includes "
             "the boarding buffer. Completion and incompletion rates cover all attempts. The intended "
             "connection miss rate covers only arrivals with a feasible scheduled connection.")
    st.write("These hypothetical shifts apply to this connection and service window. Results depend on "
             "timetable and pedestrian map quality. The model omits live vehicle observations, passenger "
             "demand, capacity and effects on other connections.")
