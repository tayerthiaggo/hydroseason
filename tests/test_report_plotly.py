import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydroseason._catchment import analyze_catchment
from hydroseason._report_export import build_monthly_export
from hydroseason._report_plotly import (
    event_duration_figure,
    hydro_year_figure,
    low_spell_duration_figure,
    rainfall_context_figure,
    secondary_figure,
    timeline_figure,
)

_CLIMATOLOGY_TRACE = "Long-term monthly water extent (+/-1 std)"


def _marginal_frames():
    """A record with strong amplitude but per-year peak timing that wanders.

    Clears the SNR gate while failing the phase-IQR gate, which is the case
    that routes to an imposed fixed climatological window.
    """
    rng = np.random.default_rng(0)
    dates = pd.date_range("2004-01-01", periods=12 * 20, freq="MS")
    peak_by_year = {year: 1 + rng.integers(-2, 3) for year in range(2004, 2025)}
    values = [
        max(
            0.05,
            6.0
            + 5.0 * np.cos(2 * np.pi * (date.month - peak_by_year[date.year]) / 12)
            + rng.normal(0, 0.8),
        )
        for date in dates
    ]
    extent = pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates)
    analysis = analyze_catchment(extent, phase_model="rule_based", n_bootstrap=20)
    # Assert the premise: these values are drawn from a seeded generator, and a
    # change in draw order would quietly turn this into a seasonal record,
    # leaving every test below asserting nothing about the imposed-window path.
    assert analysis.regime.regime == "marginal"
    assert analysis.route == "fixed_climatological_window"
    return build_monthly_export(extent, analysis=analysis), analysis


@pytest.fixture
def marginal_data():
    return _marginal_frames()


@pytest.fixture
def aseasonal_with_events_data():
    """An aseasonal record with a handful of real wet events (not zero)."""
    rng = np.random.default_rng(3)
    dates = pd.date_range("2010-01-01", periods=120, freq="MS")
    extent = pd.DataFrame(
        {"extent_pct": np.abs(rng.normal(0.15, 0.12, 120)), "invalid_pct": 0.0},
        index=dates,
    )
    analysis = analyze_catchment(extent, phase_model="rule_based", n_bootstrap=20)
    assert not analysis.events.events.empty
    return build_monthly_export(extent, analysis=analysis), analysis


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

    assert figure["layout"]["yaxis2"]["title"] == {"text": "Rainfall (mm)"}
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


def test_timeline_draws_one_line_at_the_shared_trough_boundary():
    """A year's start (trough+1 month) shares its boundary with the prior
    year's trough -- only the trough line is drawn, not both.

    Boundaries used to be drawn at both the trough and the following year's
    start month, rendering two dashed lines a month apart for what is
    really one cycle boundary.
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

    assert "2024-11-01" in boundaries
    assert "2024-12-01" not in boundaries


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


def test_timeline_draws_start_line_when_no_previous_trough_anchors_it():
    """The record's opening year has no prior trough, so its start month
    still needs its own boundary line (e.g. a record starting Jan 2005)."""
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
                "hy_year": [2024],
                "hy_start": [pd.Timestamp("2024-10-01")],
                "hy_end": [pd.Timestamp("2024-11-01")],
                "trough_month": [pd.Timestamp("2024-11-01")],
                "confidence": ["high"],
                "boundary_status": ["complete"],
            }
        )
    )

    figure = timeline_figure(monthly, analysis)
    boundaries = {
        shape["x0"]
        for shape in figure["layout"]["shapes"]
        if shape.get("type") == "line" and shape.get("name", "").startswith("HY ")
    }

    assert "2024-10-01" in boundaries
    assert "2024-11-01" in boundaries


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


def test_secondary_figure_is_climatology_on_every_route(seasonal_data, marginal_data):
    """Seasonal Context describes the observations, so no route may withhold it."""
    for monthly, analysis in (seasonal_data, marginal_data):
        figure = secondary_figure(monthly, analysis)
        assert _CLIMATOLOGY_TRACE in [trace["name"] for trace in figure["data"]]
        assert len(figure["data"][-1]["x"]) == 12
        json.dumps(figure, allow_nan=False)


def test_aseasonal_route_still_gets_a_climatology():
    """The flat profile is itself the evidence for aseasonality; drawing it is the point."""
    rng = np.random.default_rng(3)
    dates = pd.date_range("2010-01-01", periods=120, freq="MS")
    extent = pd.DataFrame(
        {"extent_pct": np.abs(rng.normal(0.15, 0.12, 120)), "invalid_pct": 0.0},
        index=dates,
    )
    analysis = analyze_catchment(extent, phase_model="rule_based", n_bootstrap=20)
    monthly = build_monthly_export(extent, analysis=analysis)

    assert analysis.route == "event_characterisation"
    figure = secondary_figure(monthly, analysis)
    assert figure["data"][-1]["name"] == _CLIMATOLOGY_TRACE
    assert len(figure["data"][-1]["x"]) == 12


def test_event_duration_figure_is_its_own_panel(aseasonal_with_events_data):
    """Events no longer displace the climatology; both panels can coexist."""
    monthly, analysis = aseasonal_with_events_data
    n_events = len(analysis.events.events)
    figure = event_duration_figure(analysis)
    assert figure is not None
    assert figure["data"][0]["type"] == "bar"
    assert len(figure["data"][0]["x"]) == n_events
    assert len(figure["data"][0]["y"]) == n_events
    assert figure["layout"]["yaxis"]["title"] == {"text": "Duration (months)"}
    json.dumps(figure, allow_nan=False)
    # The climatology is still produced for the same analysis.
    assert secondary_figure(monthly, analysis)["data"][-1]["name"] == _CLIMATOLOGY_TRACE


def test_low_spell_duration_figure_is_one_bar_per_spell(marginal_data):
    """Low-extent spells get the same discrete-event treatment as wet events."""
    _, analysis = marginal_data
    n_spells = len(analysis.events.low_spells)
    assert n_spells > 0
    figure = low_spell_duration_figure(analysis)
    assert figure is not None
    assert figure["data"][0]["type"] == "bar"
    assert len(figure["data"][0]["x"]) == n_spells
    assert len(figure["data"][0]["y"]) == n_spells
    assert figure["layout"]["yaxis"]["title"] == {"text": "Duration (months)"}
    json.dumps(figure, allow_nan=False)


def test_low_spell_duration_figure_is_none_without_spells(seasonal_data):
    _, analysis = seasonal_data
    assert analysis.events.low_spells.empty
    assert low_spell_duration_figure(analysis) is None


def test_event_duration_figure_is_none_without_events(marginal_data):
    """A record with no wet events omits the panel rather than drawing empty axes."""
    _, analysis = marginal_data
    assert analysis.events.events.empty
    assert event_duration_figure(analysis) is None

    detached = SimpleNamespace(events=SimpleNamespace(events=pd.DataFrame()))
    assert event_duration_figure(detached) is None


def test_imposed_boundaries_labelled_but_drawn_like_detected(seasonal_data, marginal_data):
    """The legend names an imposed window; the marker glyph itself is unchanged.

    Markers stay visually identical across routes so a reader scanning the
    Monthly Surface Water Extent chart sees one consistent marker language;
    the "(imposed)" legend text is what carries the provenance distinction.
    """
    _, marginal_analysis = marginal_data
    assert marginal_analysis.route == "fixed_climatological_window"

    imposed = timeline_figure(*marginal_data)
    detected = timeline_figure(*seasonal_data)

    imposed_markers = [t for t in imposed["data"] if str(t.get("name", "")).startswith("HY")]
    detected_markers = [t for t in detected["data"] if str(t.get("name", "")).startswith("HY")]

    assert imposed_markers, "imposed run should still draw markers"
    assert all("(imposed)" in trace["name"] for trace in imposed_markers)
    assert all("(imposed)" not in trace["name"] for trace in detected_markers)

    imposed_by_base_name = {trace["name"].replace(" (imposed)", ""): trace for trace in imposed_markers}
    detected_by_name = {trace["name"]: trace for trace in detected_markers}
    for base_name, imposed_trace in imposed_by_base_name.items():
        detected_trace = detected_by_name[base_name]
        assert imposed_trace["marker"]["symbol"] == detected_trace["marker"]["symbol"]
        assert imposed_trace["marker"]["color"] == detected_trace["marker"]["color"]


def test_imposed_phase_bands_are_lighter_than_detected(seasonal_data, marginal_data):
    def opacity(figure):
        shapes = [
            shape
            for shape in figure["layout"]["shapes"]
            if str(shape.get("name", "")).startswith("phase:")
        ]
        assert shapes, "expected phase bands"
        return shapes[0]["opacity"]

    assert opacity(timeline_figure(*marginal_data)) < opacity(timeline_figure(*seasonal_data))


def test_marginal_route_labels_phases_and_troughs(marginal_data):
    """The imposed window carries the same monthly products as a detected one."""
    monthly, analysis = marginal_data
    assert analysis.monthly_phase is not None
    assert set(monthly["phase"].unique()) - {"unspecified"}
    assert analysis.hydro_years["trough_month"].notna().all()
    assert (analysis.hydro_years["boundary_basis"] == "imposed_fixed_window").all()
    assert monthly["is_hy_trough"].sum() > 0


def test_every_axis_carries_a_unit(
    seasonal_data, marginal_data, seasonal_data_with_rainfall, aseasonal_with_events_data
):
    """Every rendered axis states its unit -- a bare 'Duration' or 'Extent' invites misreading."""
    monthly, analysis = seasonal_data
    _, marginal_analysis = marginal_data
    rain_monthly, _ = seasonal_data_with_rainfall
    _, event_analysis = aseasonal_with_events_data

    event_fig = event_duration_figure(event_analysis)
    low_spell_fig = low_spell_duration_figure(marginal_analysis)
    assert event_fig is not None
    assert low_spell_fig is not None

    figures = [
        # Monthly Surface Water Extent's x-axis is deliberately untitled (the
        # dates are self-evident from the tick labels); its y-axis still
        # needs one, so it stays in this check via a dedicated skip below.
        secondary_figure(monthly, analysis),
        event_fig,
        low_spell_fig,
        rainfall_context_figure(rain_monthly),
    ]
    timeline = timeline_figure(monthly, analysis)
    assert timeline["layout"]["xaxis"].get("title") is None
    assert timeline["layout"]["yaxis"]["title"] == {"text": "Water Extent (%)"}

    for figure in figures:
        for axis_key in ("xaxis", "yaxis", "yaxis2"):
            axis = figure["layout"].get(axis_key)
            if axis is None:
                continue
            title = axis.get("title")
            trace_names = [t.get("name") for t in figure["data"]]
            assert title, f"{axis_key} on {trace_names} has no title"
            # The vendored Plotly.js build silently drops a bare-string axis
            # title (renders untitled, no error), so every axis title in this
            # module must be the {"text": ...} object form -- a plain string
            # here is a real bug, not an equivalent shorthand.
            assert isinstance(title, dict) and "text" in title, (
                f"{axis_key} title {title!r} on {trace_names} is not a "
                '{"text": ...} object; a bare string silently renders as no title'
            )
            text = title["text"]
            if axis_key == "xaxis":
                # X-axes here are Date/Month/category labels, not measured
                # quantities -- a title is required, but not a unit suffix.
                continue
            unit_bearing = any(marker in text for marker in ("%", "mm", "month"))
            assert unit_bearing, f"{axis_key} title {text!r} on {trace_names} does not state a unit"
