import numpy as np
import pandas as pd

from hydroseason.fixed_season import (
    circular_climatology,
    circular_stats,
    hydro_year_start_after_min_month,
    hydro_year_start_driest_6_months,
    identify_fixed_hydro_year,
)


def test_circular_stats_unimodal():
    # Wet peak in January
    values = np.array([220, 200, 160, 50, 18, 3, 0, 0, 1, 25, 130, 210], dtype=float)
    stats = circular_stats(values)
    assert stats.peak_month == 1
    assert stats.concentration_R > 0.3
    assert not stats.is_uniform


def test_circular_stats_uniform():
    stats = circular_stats(np.ones(12) * 50)
    assert stats.is_uniform
    assert stats.concentration_R < 0.05


def test_circular_stats_bimodal():
    # Two peaks: Mar-Apr and Oct-Nov
    values = np.array([20, 40, 120, 130, 60, 20, 10, 15, 30, 120, 130, 60], dtype=float)
    stats = circular_stats(values)
    assert stats.is_bimodal


def test_circular_climatology(monthly_df: pd.DataFrame):
    clim, start, stats = circular_climatology(monthly_df)
    assert len(clim) == 12
    assert set(clim["Season"].unique()).issubset({"Wet", "Dry", "Unclassified"})
    assert start is None or 1 <= start <= 12
    assert 0.0 <= stats.concentration_R <= 1.0


def test_identify_fixed_hydro_year_accepts_value_col(monthly_df: pd.DataFrame):
    """Regression: previously hardcoded 'Rainfall_mm' and 'Month'."""
    renamed = monthly_df.rename(columns={"Rainfall_mm": "Q_mm"})
    df, start = identify_fixed_hydro_year(renamed, value_col="Q_mm")
    assert len(df) == 12
    assert start is None or 1 <= start <= 12


def test_alt_methods(monthly_df: pd.DataFrame):
    s1, months = hydro_year_start_driest_6_months(monthly_df)
    s2, min_m = hydro_year_start_after_min_month(monthly_df)
    assert 1 <= s1 <= 12 and len(months) == 6
    assert 1 <= s2 <= 12 and 1 <= min_m <= 12
