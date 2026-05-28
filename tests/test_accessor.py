"""Tests for the pandas ``df.hydroseason`` accessor."""

import pandas as pd
import pytest
import hydroseason  # noqa: F401 — registers the accessor


@pytest.fixture
def paper_df():
    return pd.read_csv("tests/fixtures/tayer2026_input.csv")


def test_accessor_classify(paper_df: pd.DataFrame):
    result = paper_df.hydroseason.classify()
    assert isinstance(result, pd.DataFrame)
    assert "SeasonType" in result.columns
    assert "Hydro_Year" in result.columns


def test_accessor_delineate(paper_df: pd.DataFrame):
    arts = paper_df.hydroseason.delineate()
    assert arts.diagnostics.regime in {"non_seasonal", "borderline", "seasonal"}
    assert arts.diagnostics.stl_strength >= 0


def test_accessor_diagnostics(paper_df: pd.DataFrame):
    diag = paper_df.hydroseason.diagnostics()
    assert hasattr(diag, "stl_strength")
    assert hasattr(diag, "walsh_lawler_si")


def test_accessor_plot_timeline(paper_df: pd.DataFrame):
    # Run pipeline first, attach results so accessor doesn't re-run
    result = paper_df.hydroseason.classify()
    fig = result.hydroseason.plot_timeline()
    assert fig is not None


def test_accessor_repr(paper_df: pd.DataFrame):
    assert "HydroSeasonAccessor" in repr(paper_df.hydroseason)
