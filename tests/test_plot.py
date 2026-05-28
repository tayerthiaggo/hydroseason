"""Smoke tests for HydroSeason.plot and HydroSeason.report.

Verifies that all plot functions return ``plotly.graph_objects.Figure``
and that the HTML report is written without error.
"""

import pytest
import pandas as pd
import plotly.graph_objects as go

import hydroseason
from hydroseason.pipeline import delineate_monthly_dataframe


@pytest.fixture
def paper_df():
    return pd.read_csv("tests/fixtures/tayer2026_input.csv")


@pytest.fixture
def artifacts(paper_df):
    return delineate_monthly_dataframe(paper_df)


def test_plot_season_timeline(artifacts):
    fig = hydroseason.plot_season_timeline(artifacts.result)
    assert isinstance(fig, go.Figure)


def test_plot_season_timeline_keeps_transition_rows(artifacts):
    result = artifacts.result.copy()
    result.loc[result.index[:2], "SeasonType"] = "Transition"
    fig = hydroseason.plot_season_timeline(result)
    assert isinstance(fig, go.Figure)
    assert any(trace.name == "Transition" for trace in fig.data)


def test_plot_monthly_climatology(artifacts):
    fig = hydroseason.plot_monthly_climatology(artifacts.result, artifacts.fixed_monthly)
    assert isinstance(fig, go.Figure)


def test_plot_stl_decomposition(paper_df):
    from hydroseason.plot import plot_stl_decomposition
    fig = plot_stl_decomposition(paper_df)
    assert isinstance(fig, go.Figure)


def test_plot_annual_metrics(artifacts):
    fig = hydroseason.plot_annual_metrics(artifacts.result)
    assert isinstance(fig, go.Figure)


def test_plot_diagnostics_table(artifacts):
    from hydroseason.plot import plot_diagnostics_table
    fig = plot_diagnostics_table(artifacts.diagnostics)
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
    for heading in ["Season Timeline", "Monthly Climatology", "Annual Wet", "STL", "Diagnostics", "Metrics"]:
        assert heading in content


def test_display_summary(artifacts):
    from hydroseason.report import display_summary
    card = display_summary(artifacts)
    assert hasattr(card, "_repr_html_") or hasattr(card, "data")
    raw = card.data if hasattr(card, "data") else card._repr_html_()
    assert "HydroSeason" in raw
    assert "Walsh-Lawler" in raw
