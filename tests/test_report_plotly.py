import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydroseason._catchment import analyze_catchment
from hydroseason._report_export import build_monthly_export
from hydroseason._report_plotly import (
    hydro_year_figure,
    rainfall_context_figure,
    secondary_figure,
    timeline_figure,
)


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
    assert "Median Baseline" in names
    assert "Invalid Coverage (%)" not in names
    primary_names = [
        trace["name"] for trace in figure["data"] if not trace.get("meta", {}).get("phase_legend")
    ]
    assert primary_names[:6] == [
        "Water Extent (%)", "Reference Median", "Median Baseline",
        "HY Peak", "HY Mid Dry", "HY End Dry",
    ]
    assert next(trace for trace in figure["data"] if trace["name"] == "Reference Median")["visible"] == "legendonly"
    assert next(trace for trace in figure["data"] if trace["name"] == "Median Baseline")["visible"] == "legendonly"
    marker_names = {
        trace.get("name") for trace in figure["data"] if trace.get("mode") == "markers"
    }
    assert marker_names == {"HY Peak", "HY Mid Dry", "HY End Dry"}
    assert {"phase:wet", "phase:recession", "phase:dry"} <= {
        shape["name"] for shape in phase_shapes
    }
    phase_legend_names = {
        trace["name"] for trace in figure["data"] if trace.get("meta", {}).get("phase_legend")
    }
    assert phase_legend_names == {"Recovery", "Wet", "Recession", "Dry"}
    assert figure["layout"]["yaxis"]["type"] == "linear"
    assert figure["layout"]["xaxis"]["rangeslider"]["visible"] is False
    assert figure["layout"]["dragmode"] == "pan"
    assert not any(
        shape.get("name", "").startswith("low confidence:")
        for shape in figure["layout"]["shapes"]
    )
    assert figure["config"]["scrollZoom"] is True

    assert all(
        trace["marker"]["size"] == 8
        for trace in figure["data"]
        if trace.get("name") in {"HY Peak", "HY Mid Dry", "HY End Dry"}
    )

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
    intervals = [
        shape
        for shape in figure["layout"]["shapes"]
        if shape.get("name", "").startswith("HY ") and shape.get("type") == "rect"
    ]
    assert {(shape["x0"], shape["x1"]) for shape in intervals} == expected_intervals


def test_timeline_adds_rainfall_only_when_supplied(seasonal_data, seasonal_data_with_rainfall):
    monthly_no_rain, analysis = seasonal_data
    monthly_rain, _ = seasonal_data_with_rainfall

    without = timeline_figure(monthly_no_rain, analysis)
    with_rain = timeline_figure(monthly_rain, analysis)

    assert all(trace.get("name") != "Rainfall" for trace in without["data"])
    assert any(trace.get("name") == "Rainfall" for trace in with_rain["data"])


def test_timeline_uses_single_rainfall_secondary_axis(seasonal_data_with_rainfall):
    monthly, analysis = seasonal_data_with_rainfall

    figure = timeline_figure(monthly, analysis)

    assert figure["layout"]["yaxis2"]["title"] == "Rainfall (mm)"
    assert "yaxis3" not in figure["layout"]
    assert "domain" not in figure["layout"]["xaxis"]


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


def test_timeline_draws_opening_boundary_for_year_starting_off_a_trough():
    """A hydro-year whose start is not a trough still needs a left-hand edge.

    Boundaries used to be drawn only at trough months, so the final partial
    cycle -- which opens the month after the previous trough -- rendered with
    no opening line and visually merged into the preceding year.
    """
    monthly = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2024-10-01", "2024-11-01", "2024-12-01", "2025-01-01"]
            ),
            "extent_pct": [0.05, 0.03, 0.07, 0.26],
            "invalid_pct": [1.0, 1.0, 1.0, 1.0],
            "phase": ["recession", "dry", "wet", "wet"],
            "hy_year": [2024, 2024, 2025, 2025],
        }
    )
    analysis = SimpleNamespace(
        hydro_years=pd.DataFrame(
            {
                "hy_year": [2024, 2025],
                "hy_start": [pd.Timestamp("2024-02-01"), pd.Timestamp("2024-12-01")],
                "hy_end": [pd.Timestamp("2024-11-01"), pd.Timestamp("2025-11-01")],
                "trough_month": [
                    pd.Timestamp("2024-11-01"),
                    pd.Timestamp("2025-11-01"),
                ],
                "confidence": ["high", "medium"],
                "boundary_status": ["complete", "provisional"],
            }
        )
    )

    figure = timeline_figure(monthly, analysis)
    boundaries = {
        shape["x0"]
        for shape in figure["layout"]["shapes"]
        if shape.get("type") == "line" and shape.get("name", "").startswith("HY ")
    }

    assert "2024-12-01" in boundaries
    assert "2024-11-01" in boundaries


def test_timeline_does_not_duplicate_a_shared_cycle_boundary():
    """Consecutive years sharing a boundary date must draw it once."""
    monthly = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-10-01", "2024-11-01", "2024-12-01"]),
            "extent_pct": [0.05, 0.03, 0.07],
            "invalid_pct": [1.0, 1.0, 1.0],
            "phase": ["recession", "dry", "wet"],
            "hy_year": [2024, 2024, 2025],
        }
    )
    analysis = SimpleNamespace(
        hydro_years=pd.DataFrame(
            {
                "hy_year": [2024, 2025],
                "hy_start": [pd.Timestamp("2024-02-01"), pd.Timestamp("2024-11-01")],
                "hy_end": [pd.Timestamp("2024-11-01"), pd.Timestamp("2025-11-01")],
                "trough_month": [
                    pd.Timestamp("2024-11-01"),
                    pd.Timestamp("2025-11-01"),
                ],
                "confidence": ["high", "medium"],
                "boundary_status": ["complete", "provisional"],
            }
        )
    )

    figure = timeline_figure(monthly, analysis)
    lines = [
        shape
        for shape in figure["layout"]["shapes"]
        if shape.get("type") == "line" and shape.get("name", "").startswith("HY ")
    ]

    assert [shape["x0"] for shape in lines].count("2024-11-01") == 1


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

    assert extent["customdata"][0] == [0.0, -2.0, "recovery", 2020, "HY Peak"]
    assert extent["customdata"][1] == [12.5, 10.0, "wet", 2020, "None"]
    assert extent["hovertemplate"] == (
        "Date: %{x}<br>Water Extent: %{customdata[0]}%<br>"
        "Reference Median: %{customdata[1]}%<br>"
        "Phase: %{customdata[2]}<br>"
        "HY Year: %{customdata[3]}<br>Marker Status: %{customdata[4]}<extra></extra>"
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


def test_rainfall_context_figure_pairs_monthly_climatologies(
    seasonal_data_with_rainfall,
):
    monthly, _ = seasonal_data_with_rainfall
    figure = rainfall_context_figure(monthly)

    assert [trace["name"] for trace in figure["data"]] == [
        "Mean Monthly Rainfall (mm)",
        "Mean Monthly Extent (%)",
    ]
    assert figure["data"][0]["type"] == "bar"
    assert figure["data"][1]["type"] == "scatter"
    assert len(figure["data"][0]["x"]) == 12
    json.dumps(figure, allow_nan=False)


def test_rainfall_context_figure_is_none_without_rainfall(seasonal_data):
    monthly, _ = seasonal_data
    assert rainfall_context_figure(monthly) is None
