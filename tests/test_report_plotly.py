import json

import numpy as np
import pandas as pd
import pytest

from hydroseason._catchment import analyze_catchment
from hydroseason._report_export import build_monthly_export
from hydroseason._report_plotly import hydro_year_figure, secondary_figure, timeline_figure


@pytest.fixture
def seasonal_data():
    dates = pd.date_range("2010-01-01", "2015-12-01", freq="MS")
    records = []
    for date in dates:
        month = date.month
        val = 10.0 + 30.0 * np.sin(2 * np.pi * (month - 1) / 12) + np.random.normal(0, 0.5)
        records.append({"extent_pct": max(0.0, min(100.0, val)), "invalid_pct": 0.0})
    df = pd.DataFrame(records, index=dates)
    analysis = analyze_catchment(df, phase_model="rule_based", n_bootstrap=40)
    monthly = build_monthly_export(df, analysis=analysis)
    return monthly, analysis


@pytest.fixture
def seasonal_data_with_rainfall():
    dates = pd.date_range("2010-01-01", "2015-12-01", freq="MS")
    records = []
    rain_records = []
    for date in dates:
        month = date.month
        val = 10.0 + 30.0 * np.sin(2 * np.pi * (month - 1) / 12) + np.random.normal(0, 0.5)
        records.append({"extent_pct": max(0.0, min(100.0, val)), "invalid_pct": 0.0})
        rain_records.append({"rainfall_mm": 50.0 + 20.0 * np.sin(2 * np.pi * month / 12)})
    df = pd.DataFrame(records, index=dates)
    rain_df = pd.DataFrame(rain_records, index=dates)
    analysis = analyze_catchment(df, phase_model="rule_based", n_bootstrap=40)
    monthly = build_monthly_export(df, analysis=analysis, rainfall=rain_df)
    return monthly, analysis


def test_plotly_figures_are_light_and_serializable(seasonal_data):
    monthly, analysis = seasonal_data
    figure = timeline_figure(monthly, analysis)
    json.dumps(figure, allow_nan=False)
    assert figure["layout"]["paper_bgcolor"] == "#ffffff"
    assert figure["layout"]["plot_bgcolor"] == "#f8fafc"
    assert figure["config"]["responsive"] is True
    assert figure["config"]["displaylogo"] is False
    assert figure["config"]["scrollZoom"] is True
    assert "lasso2d" in figure["config"]["modeBarButtonsToRemove"]
    assert "select2d" in figure["config"]["modeBarButtonsToRemove"]


def test_timeline_contains_phase_context_quality_and_scale_controls(seasonal_data):
    monthly, analysis = seasonal_data
    figure = timeline_figure(monthly, analysis)
    names = {trace.get("name") for trace in figure["data"]}
    phase_shapes = [shape for shape in figure["layout"]["shapes"] if shape.get("name", "").startswith("phase:")]

    assert "Water Extent (%)" in names
    assert "Reference Median" in names
    assert "Invalid Coverage (%)" in names
    assert {"HY Peak", "HY Mid Dry", "HY End Dry"} <= names
    assert {"phase:recovery", "phase:wet", "phase:recession", "phase:dry"} <= {
        shape["name"] for shape in phase_shapes
    }
    assert figure["layout"]["yaxis"]["type"] == "linear"
    assert figure["layout"]["yaxis2"]["title"] == "Invalid Coverage (%)"
    assert figure["layout"]["xaxis"]["rangeslider"]["visible"] is True
    assert figure["config"]["scrollZoom"] is True

    mid_dry = next(trace for trace in figure["data"] if trace.get("name") == "HY Mid Dry")
    expected = [pd.Timestamp(value).strftime("%Y-%m-%d") for value in analysis.hydro_years["temporal_mid_dry_month"]]
    assert mid_dry["x"] == expected


def test_hydro_year_figure_contains_intervals_labels_and_boundary_markers(seasonal_data):
    monthly, analysis = seasonal_data
    figure = hydro_year_figure(monthly, analysis)

    assert any(trace.get("name") == "Hydrological-year extent" for trace in figure["data"])
    assert {"HY Peak", "HY Mid Dry", "HY End Dry"} <= {
        trace.get("name") for trace in figure["data"]
    }
    assert any(annotation.get("text", "").startswith("HY ") for annotation in figure["layout"]["annotations"])
    assert any(shape.get("name", "").startswith("HY ") for shape in figure["layout"]["shapes"])
    assert figure["layout"]["xaxis"]["rangeslider"]["visible"] is False

    intervals = [shape for shape in figure["layout"]["shapes"] if shape.get("name", "").startswith("HY ")]
    expected_intervals = {
        (pd.Timestamp(row.hy_start).strftime("%Y-%m-%d"), pd.Timestamp(row.hy_end).strftime("%Y-%m-%d"))
        for row in analysis.hydro_years.itertuples()
    }
    assert {(shape["x0"], shape["x1"]) for shape in intervals} >= expected_intervals


def test_timeline_adds_rainfall_only_when_supplied(seasonal_data, seasonal_data_with_rainfall):
    monthly_no_rain, analysis = seasonal_data
    monthly_rain, _ = seasonal_data_with_rainfall

    without = timeline_figure(monthly_no_rain, analysis)
    with_rain = timeline_figure(monthly_rain, analysis)

    assert all(trace.get("name") != "Rainfall" for trace in without["data"])
    assert any(trace.get("name") == "Rainfall" for trace in with_rain["data"])


def test_secondary_figure_is_light_and_serializable(seasonal_data):
    monthly, analysis = seasonal_data
    figure = secondary_figure(monthly, analysis)
    json.dumps(figure, allow_nan=False)
    assert figure["layout"]["paper_bgcolor"] == "#ffffff"
    assert figure["layout"]["plot_bgcolor"] == "#f8fafc"
