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


def test_circular_stats_contiguous_wet_block_not_bimodal():
    # One Nov-Apr wet season can have a strong second harmonic, but it is not
    # bimodal unless high-rain months split into separated wet runs.
    values = np.array([226, 194, 100, 25, 19, 8, 9, 2, 3, 14, 48, 119], dtype=float)
    stats = circular_stats(values)
    assert not stats.is_bimodal


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


def test_label_wet_dry_bimodal_median_zero():
    from hydroseason.fixed_season import _label_wet_dry_bimodal
    # 7 zeros, 5 non-zeros. Median is 0.0.
    values = np.array([100.0, 0.0, 100.0, 0.0, 50.0, 0.0, 0.0, 0.0, 0.0, 10.0, 0.0, 5.0])
    seasons = _label_wet_dry_bimodal(values)
    # 0.0 values should be Dry, non-zero should be Wet
    for val, season in zip(values, seasons):
        if val == 0.0:
            assert season == "Dry"
        else:
            assert season == "Wet"


def test_label_wet_dry_unimodal_adaptive():
    from hydroseason.fixed_season import _label_wet_dry_unimodal

    # 1. Sharp peak (R >= 0.833) -> should produce 3 wet months (peak +/- 1)
    # Peak month: Jan (idx 0, month 1)
    values_sharp = np.array([500.0, 10.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 10.0])
    seasons_sharp = _label_wet_dry_unimodal(values_sharp, 1)
    assert (seasons_sharp == "Wet").sum() == 3
    # Wet months should be Dec (12), Jan (1), Feb (2)
    assert seasons_sharp[0] == "Wet"  # Jan
    assert seasons_sharp[1] == "Wet"  # Feb
    assert seasons_sharp[11] == "Wet"  # Dec

    # 2. Moderate peak (0.50 <= R < 0.833) -> should produce 5 wet months (peak +/- 2)
    # Peak month: Jan (idx 0, month 1)
    values_mod = np.array([220, 200, 160, 50, 18, 3, 0, 0, 1, 25, 130, 210], dtype=float)
    seasons_mod = _label_wet_dry_unimodal(values_mod, 1)
    assert (seasons_mod == "Wet").sum() == 5
    # Wet months should be Nov (11), Dec (12), Jan (1), Feb (2), Mar (3)
    assert seasons_mod[0] == "Wet"
    assert seasons_mod[1] == "Wet"
    assert seasons_mod[2] == "Wet"
    assert seasons_mod[10] == "Wet"
    assert seasons_mod[11] == "Wet"

    # 3. Diffuse peak (R < 0.50) -> should produce 7 wet months (peak +/- 3)
    # Peak month: Jan (idx 0, month 1)
    values_diffuse = np.array([120, 110, 100, 90, 80, 50, 20, 10, 20, 50, 80, 100], dtype=float)
    seasons_diffuse = _label_wet_dry_unimodal(values_diffuse, 1)
    assert (seasons_diffuse == "Wet").sum() == 7

