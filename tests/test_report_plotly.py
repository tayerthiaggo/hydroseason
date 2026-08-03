import json
from types import SimpleNamespace

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
    marker_names = {
        trace.get("name") for trace in figure["data"] if trace.get("mode") == "markers"
    }
    assert marker_names == {"HY Peak", "HY Mid Dry", "HY End Dry"}
    assert {"phase:recovery", "phase:wet", "phase:recession", "phase:dry"} == {
        shape["name"] for shape in phase_shapes
    }
    assert figure["layout"]["yaxis"]["type"] == "linear"
    assert figure["layout"]["yaxis2"]["title"] == "Invalid Coverage (%)"
    assert figure["layout"]["xaxis"]["rangeslider"]["visible"] is True
    assert figure["config"]["scrollZoom"] is True

    mid_dry = next(trace for trace in figure["data"] if trace.get("name") == "HY Mid Dry")
    expected = [
        pd.Timestamp(value).strftime("%Y-%m-%d")
        for value in analysis.hydro_years["temporal_mid_dry_month"].dropna()
    ]
    assert mid_dry["x"] == expected


def test_hydro_year_figure_contains_intervals_labels_and_boundary_markers(seasonal_data):
    monthly, analysis = seasonal_data
    figure = hydro_year_figure(monthly, analysis)

    assert any(trace.get("name") == "Hydrological-year extent" for trace in figure["data"])
    marker_names = {
        trace.get("name") for trace in figure["data"] if trace.get("mode") == "markers"
    }
    assert marker_names == {"HY Peak", "HY Mid Dry", "HY End Dry"}
    assert any(annotation.get("text", "").startswith("HY ") for annotation in figure["layout"]["annotations"])
    assert figure["layout"]["xaxis"]["rangeslider"]["visible"] is False

    expected_intervals = {
        (pd.Timestamp(row.hy_start).strftime("%Y-%m-%d"), pd.Timestamp(row.hy_end).strftime("%Y-%m-%d"))
        for row in analysis.hydro_years.itertuples()
        if pd.notna(row.hy_start) and pd.notna(row.hy_end)
    }
    intervals = [shape for shape in figure["layout"]["shapes"] if shape.get("name", "").startswith("HY ")]
    assert all(shape.get("type") == "rect" for shape in intervals)
    assert {(shape["x0"], shape["x1"]) for shape in intervals} == expected_intervals


def test_timeline_adds_rainfall_only_when_supplied(seasonal_data, seasonal_data_with_rainfall):
    monthly_no_rain, analysis = seasonal_data
    monthly_rain, _ = seasonal_data_with_rainfall

    without = timeline_figure(monthly_no_rain, analysis)
    with_rain = timeline_figure(monthly_rain, analysis)

    assert all(trace.get("name") != "Rainfall" for trace in without["data"])
    assert any(trace.get("name") == "Rainfall" for trace in with_rain["data"])


def test_timeline_separates_invalid_and_rainfall_axes(seasonal_data_with_rainfall):
    monthly, analysis = seasonal_data_with_rainfall

    figure = timeline_figure(monthly, analysis)

    assert figure["layout"]["xaxis"]["domain"] == [0.0, 0.82]
    assert figure["layout"]["yaxis2"]["anchor"] == "free"
    assert figure["layout"]["yaxis2"]["position"] == 0.84
    assert figure["layout"]["yaxis3"]["anchor"] == "free"
    assert figure["layout"]["yaxis3"]["position"] == 1.0
    assert figure["layout"]["margin"]["r"] >= 120


def test_extent_trace_preserves_non_positive_values_for_log_mode_hover(seasonal_data):
    monthly, analysis = seasonal_data
    monthly = monthly.copy()
    monthly.loc[0, "extent_pct"] = 0.0
    monthly.loc[1, "extent_pct"] = -1.0

    figure = timeline_figure(monthly, analysis)
    extent = next(trace for trace in figure["data"] if trace.get("name") == "Water Extent (%)")

    assert extent["meta"]["log_safe_y"][:2] == [0.02, 0.02]
    assert extent["meta"]["original_y"][:2] == [0.0, -1.0]
    assert [row[0] for row in extent["customdata"][:2]] == [0.0, -1.0]
    assert "%{customdata[0]}" in extent["hovertemplate"]


def test_timeline_extent_hover_has_month_context_with_and_without_markers():
    monthly = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-01", "2020-02-01", "2020-03-01", "2020-04-01"]),
            "extent_pct": [0.0, 12.5, 30.0, 4.0],
            "reference_median_pct": [-2.0, 10.0, 20.0, 6.0],
            "invalid_pct": [4.0, 5.0, 6.0, 7.0],
            "phase": ["recovery", "wet", "recession", "dry"],
            "hy_year": [2020, 2020, 2020, 2020],
        }
    )
    analysis = SimpleNamespace(
        hydro_years=pd.DataFrame(
            {
                "hy_year": [2020],
                "peak_month": [pd.Timestamp("2020-01-01")],
                "temporal_mid_dry_month": [pd.Timestamp("2020-03-01")],
                "trough_month": [pd.Timestamp("2020-04-01")],
                "confidence": ["high"],
                "boundary_status": ["complete"],
            }
        )
    )

    figure = timeline_figure(monthly, analysis)
    extent = next(trace for trace in figure["data"] if trace.get("name") == "Water Extent (%)")

    assert extent["customdata"][0] == [0.0, -2.0, 4.0, "recovery", 2020, "HY Peak"]
    assert extent["customdata"][1] == [12.5, 10.0, 5.0, "wet", 2020, "None"]
    assert extent["hovertemplate"] == (
        "Date: %{x}<br>Water Extent: %{customdata[0]}%<br>"
        "Reference Median: %{customdata[1]}%<br>"
        "Invalid Coverage: %{customdata[2]}%<br>Phase: %{customdata[3]}<br>"
        "HY Year: %{customdata[4]}<br>Marker Status: %{customdata[5]}<extra></extra>"
    )
    assert extent["meta"]["original_y"] == [0.0, 12.5, 30.0, 4.0]


def test_reference_median_keeps_original_values_for_log_hover(seasonal_data):
    monthly, analysis = seasonal_data
    monthly = monthly.copy()
    monthly.loc[0, "reference_median_pct"] = 0.0
    monthly.loc[1, "reference_median_pct"] = -1.0

    figure = timeline_figure(monthly, analysis)
    reference = next(trace for trace in figure["data"] if trace.get("name") == "Reference Median")

    assert reference["meta"]["original_y"][:2] == [0.0, -1.0]
    assert reference["meta"]["log_safe_y"][:2] == [0.02, 0.02]
    assert reference["customdata"][:2] == [0.0, -1.0]
    assert reference["hovertemplate"] == (
        "Date: %{x}<br>Reference Median: %{customdata}%<extra></extra>"
    )


def test_secondary_figure_is_light_and_serializable(seasonal_data):
    monthly, analysis = seasonal_data
    figure = secondary_figure(monthly, analysis)
    json.dumps(figure, allow_nan=False)
    assert figure["layout"]["paper_bgcolor"] == "#ffffff"
    assert figure["layout"]["plot_bgcolor"] == "#f8fafc"
