"""Tests for the pandas ``df.hydroseason`` accessor."""

import pandas as pd
import pytest
import hydroseason  # noqa: F401 — registers the accessor


from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def paper_df():
    return pd.read_csv(FIXTURES / "tayer2026_input.csv")


def test_accessor_classify_rainfall_df(paper_df: pd.DataFrame):
    result = paper_df.hydroseason.classify_rainfall_df()
    assert isinstance(result, pd.DataFrame)
    assert "SeasonType" in result.columns
    assert "Hydro_Year" in result.columns


def test_accessor_classify_rainfall(paper_df: pd.DataFrame):
    arts = paper_df.hydroseason.classify_rainfall()
    assert arts.diagnostics.regime in {"non_seasonal", "borderline", "seasonal"}
    assert arts.diagnostics.stl_strength >= 0


def test_accessor_diagnostics(paper_df: pd.DataFrame):
    diag = paper_df.hydroseason.diagnostics()
    assert hasattr(diag, "stl_strength")
    assert hasattr(diag, "walsh_lawler_si")


def test_accessor_plot_timeline(paper_df: pd.DataFrame):
    # Run pipeline first, attach results so accessor doesn't re-run
    result = paper_df.hydroseason.classify_rainfall_df()
    fig = result.hydroseason.plot_timeline()
    assert fig is not None


def test_accessor_repr(paper_df: pd.DataFrame):
    assert "HydroSeasonAccessor" in repr(paper_df.hydroseason)


def test_accessor_caching(paper_df: pd.DataFrame):
    if hasattr(paper_df, "_hydroseason_cache"):
        try:
            delattr(paper_df, "_hydroseason_cache")
        except AttributeError:
            pass

    arts1 = paper_df.hydroseason.classify_rainfall()
    arts2 = paper_df.hydroseason.classify_rainfall()
    assert arts1 is arts2


def test_accessor_cache_invalidates_after_value_change(paper_df: pd.DataFrame):
    if hasattr(paper_df, "_hydroseason_cache"):
        try:
            delattr(paper_df, "_hydroseason_cache")
        except AttributeError:
            pass

    arts1 = paper_df.hydroseason.classify_rainfall()
    paper_df.loc[paper_df.index[0], "Rainfall_mm"] = (
        paper_df.loc[paper_df.index[0], "Rainfall_mm"] + 1.0
    )
    arts2 = paper_df.hydroseason.classify_rainfall()

    assert arts1 is not arts2


def test_accessor_plot_monthly_climatology_alias(paper_df: pd.DataFrame):
    fig = paper_df.hydroseason.plot_monthly_climatology()
    assert fig is not None

