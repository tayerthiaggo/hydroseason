"""Smoke tests for HydroSeason.plot and HydroSeason.report.

Verifies that all plot functions return ``plotly.graph_objects.Figure``
and that the HTML report is written without error.
"""

import pytest
import pandas as pd
import plotly.graph_objects as go
from types import SimpleNamespace

import hydroseason
from hydroseason.pipeline import classify_rainfall


@pytest.fixture
def paper_df():
    return pd.read_csv("tests/fixtures/tayer2026_input.csv")


@pytest.fixture
def artifacts(paper_df):
    return classify_rainfall(paper_df)


def test_plot_season_timeline(artifacts):
    fig = hydroseason.plot_season_timeline(artifacts.result)
    assert isinstance(fig, go.Figure)


def test_plot_season_timeline_keeps_transition_rows(artifacts):
    result = artifacts.result.copy()
    result.loc[result.index[:2], "SeasonType"] = "Transition"
    fig = hydroseason.plot_season_timeline(result)
    assert isinstance(fig, go.Figure)
    assert any(trace.name == "Transition" for trace in fig.data)


def test_plot_agg_monthly_rainfall(artifacts):
    fig = hydroseason.plot_agg_monthly_rainfall(artifacts.result, artifacts.fixed_monthly)
    assert isinstance(fig, go.Figure)


def test_plot_stl_decomposition(paper_df):
    from hydroseason.plot import plot_stl_decomposition
    fig = plot_stl_decomposition(paper_df)
    assert isinstance(fig, go.Figure)


def test_plot_annual_metrics(artifacts):
    from hydroseason.plot import DRY_COLOUR

    fig = hydroseason.plot_annual_metrics(artifacts.result)
    assert isinstance(fig, go.Figure)
    assert fig.layout.xaxis.title.text in (None, "")
    assert fig.layout.xaxis2.title.text == "Hydrological year"
    assert fig.data[1].marker.color == DRY_COLOUR


def test_plot_diagnostics_table(artifacts):
    from hydroseason.plot import plot_diagnostics_table
    fig = plot_diagnostics_table(artifacts.diagnostics)
    assert isinstance(fig, go.Figure)


def test_plot_diagnostics_table_accepts_legacy_diagnostics():
    from hydroseason.plot import plot_diagnostics_table

    legacy = SimpleNamespace(
        regime="seasonal",
        regime_source="stl",
        stl_strength=0.7,
        walsh_lawler_si=1.2,
        hydro_year_start_month=11,
        fallback_month_used=10,
        rainfall_si_override=True,
        circular_R=0.8,
        is_bimodal=False,
        is_uniform=False,
        kmeans_silhouette=None,
        threshold_firstpass=12.0,
        threshold_secondpass=5.0,
        tail_floor=12.0,
        smooth_window_used=3,
        min_core_length_used=3,
        onset_window_months_used=1,
        core_climatology_floor=4.0,
        shoulder_climatology_floor=8.0,
        shoulder_residual_threshold=None,
        validation_warnings=[],
        n_input_rows=120,
        n_rows_after_validation=120,
        n_imputed=0,
        n_unimputed=0,
        max_consecutive_missing=0,
        data_confidence="high",
    )

    fig = plot_diagnostics_table(legacy)
    assert isinstance(fig, go.Figure)


def test_plot_dashboard(artifacts):
    fig = hydroseason.plot_dashboard(artifacts)
    assert isinstance(fig, go.Figure)


def test_generate_html_report(artifacts, tmp_path):
    from hydroseason.report import generate_html_report
    out = generate_html_report(artifacts, tmp_path / "report.html")
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "HydroSeason" in content
    assert "<html" in content
    assert "Confidence note:" in content
    headings = [
        "Season Timeline",
        "Imputation and Data Quality",
        "Imputed Runs",
        "Aggregated Monthly Rainfall",
        "Annual Wet / Dry Totals",
        "STL Decomposition",
        "Per-Hydro-Year Metrics",
        "Algorithm Diagnostics",
    ]
    for heading in headings:
        assert heading in content
    assert [content.index(heading) for heading in headings] == sorted(
        content.index(heading) for heading in headings
    )
    assert "Imputed months and data quality" not in content
    assert "STL decomposition" not in content
    assert "Algorithm diagnostics" not in content
    assert "background:#D32F2F" not in content
    assert "background:#1565C0" in content


def test_display_summary(artifacts):
    from hydroseason.report import display_summary
    card = display_summary(artifacts)
    assert hasattr(card, "_repr_html_") or hasattr(card, "data")
    raw = card.data if hasattr(card, "data") else card._repr_html_()
    assert "HydroSeason" in raw
    assert "Walsh-Lawler" in raw


def test_plotly_config():
    from hydroseason.plot import PLOTLY_CONFIG
    assert PLOTLY_CONFIG.get("scrollZoom") is True
    assert PLOTLY_CONFIG.get("responsive") is True
    assert PLOTLY_CONFIG.get("displayModeBar") is True


def test_export_bundle(artifacts, tmp_path):
    """Tests HTML report + CSV/JSON export."""
    from hydroseason.report import export_bundle
    import json

    out = export_bundle(artifacts, tmp_path / "export")

    assert out.exists()
    assert (out / "report.html").exists()
    content = (out / "report.html").read_text(encoding="utf-8")
    assert "chart-container" in content
    assert "ResizeObserver" in content
    assert (out / "data" / "metrics_annual.csv").exists()
    assert (out / "data" / "diagnostics.json").exists()
    diag = json.loads((out / "data" / "diagnostics.json").read_text())
    assert "regime" in diag
    assert "walsh_lawler_si" in diag
    # Static figure export is planned for a future release.
    assert not (out / "figures").exists()
