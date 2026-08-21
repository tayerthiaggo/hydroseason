import numpy as np
import pandas as pd
import pytest

from hydroseason._circular_timing import (
    AnnualTimingSummary,
    equivalent_extremum_months,
    summarise_annual_timing,
)
from hydroseason._seasonality import _year_matrices, retained_modes
from hydroseason._state_input import candidate_weights, prepare_monthly_extent


def _year(values, year=2000):
    index = pd.date_range(f"{year}-01-01", periods=len(values), freq="MS")
    return pd.Series(values, index=index, dtype=float)


def test_flat_year_returns_every_month_not_january():
    series = _year([5.0] * 12)

    months = equivalent_extremum_months(series, kind="min", tolerance=1.0)

    assert months == tuple(range(1, 13))


def test_sharp_trough_returns_one_month():
    series = _year([50.0] * 12)
    series.iloc[6] = 1.0

    months = equivalent_extremum_months(series, kind="min", tolerance=1.0)

    assert months == (7,)


def test_tolerance_admits_near_ties_only():
    series = _year([50.0] * 12)
    series.iloc[6] = 1.0
    series.iloc[8] = 1.5
    series.iloc[10] = 9.0

    months = equivalent_extremum_months(series, kind="min", tolerance=1.0)

    assert months == (7, 9)


def test_max_kind_selects_the_peak_side():
    series = _year([5.0] * 12)
    series.iloc[3] = 90.0

    months = equivalent_extremum_months(series, kind="max", tolerance=1.0)

    assert months == (4,)


def test_all_missing_year_returns_empty():
    series = _year([np.nan] * 12)

    assert equivalent_extremum_months(series, kind="min", tolerance=1.0) == ()


def test_missing_months_are_ignored_not_treated_as_zero():
    series = _year([50.0] * 12)
    series.iloc[2] = np.nan
    series.iloc[6] = 1.0

    months = equivalent_extremum_months(series, kind="min", tolerance=1.0)

    assert months == (7,)


def test_negative_tolerance_is_rejected():
    with pytest.raises(ValueError, match="tolerance"):
        equivalent_extremum_months(_year([1.0] * 12), kind="min", tolerance=-1.0)


def test_sharp_repeated_trough_is_highly_concentrated():
    month_sets = {year: (7,) for year in range(2000, 2012)}

    summary = summarise_annual_timing(month_sets, n_resamples=200, random_state=0)

    assert summary.concentration == pytest.approx(1.0)
    assert summary.n_years == 12
    assert summary.dominant_month == 7


def test_flat_years_are_diffuse_not_concentrated():
    month_sets = {year: tuple(range(1, 13)) for year in range(2000, 2012)}

    summary = summarise_annual_timing(month_sets, n_resamples=200, random_state=0)

    assert summary.concentration == pytest.approx(0.0, abs=1e-12)
    assert summary.uniformity_p > 0.05


def test_reported_n_is_years_not_expanded_entries():
    month_sets = {2000: (6, 7, 8, 9), 2001: (7,), 2002: (7,)}

    summary = summarise_annual_timing(month_sets, n_resamples=100, random_state=0)

    assert summary.n_years == 3


def test_tied_months_do_not_narrow_the_confidence_interval():
    """One year's ambiguity must not be counted as several observations.

    An entry-indexed bootstrap would see the tied record as having more data
    and would report a *narrower* interval for the record that is objectively
    less certain. Year-indexed resampling must do the opposite.
    """
    sharp = {year: (7,) for year in range(2000, 2010)}
    tied = {year: (5, 6, 7, 8, 9) for year in range(2000, 2010)}

    sharp_summary = summarise_annual_timing(sharp, n_resamples=400, random_state=3)
    tied_summary = summarise_annual_timing(tied, n_resamples=400, random_state=3)

    sharp_width = sharp_summary.ci_high - sharp_summary.ci_low
    tied_width = tied_summary.ci_high - tied_summary.ci_low

    assert tied_width >= sharp_width
    assert tied_summary.concentration < sharp_summary.concentration


def test_tied_months_do_not_shrink_the_uniformity_p_value():
    tied = {year: tuple(range(1, 13)) for year in range(2000, 2008)}

    summary = summarise_annual_timing(tied, n_resamples=200, random_state=5)

    assert summary.uniformity_p > 0.05


def test_summary_is_deterministic_for_a_fixed_seed():
    month_sets = {2000: (12, 1), 2001: (1,), 2002: (2,), 2003: (12,), 2004: (1,)}

    first = summarise_annual_timing(month_sets, n_resamples=80, random_state=11)
    second = summarise_annual_timing(month_sets, n_resamples=80, random_state=11)

    assert first == second
    assert isinstance(first, AnnualTimingSummary)


def test_december_january_timing_is_circular():
    month_sets = {2000: (12,), 2001: (1,), 2002: (12,), 2003: (1,), 2004: (12,), 2005: (1,)}

    summary = summarise_annual_timing(month_sets, n_resamples=200, random_state=0)

    assert summary.concentration > 0.9
    assert summary.dominant_month in (12, 1)


def test_empty_input_returns_an_abstention_not_an_exception():
    summary = summarise_annual_timing({}, n_resamples=100, random_state=0)

    assert summary.n_years == 0
    assert summary.concentration is None
    assert summary.uniformity_p is None


def _matrices_from(series_values, n_periods):
    months = pd.date_range("2000-01-01", periods=n_periods, freq="MS")
    frame = pd.DataFrame({"extent_pct": series_values, "invalid_pct": 0.0}, index=months)
    prepared = prepare_monthly_extent(frame)
    weights = candidate_weights(prepared)
    _, values, matrix_weights = _year_matrices(prepared, weights)
    return values, matrix_weights


def test_unimodal_record_retains_one_peak():
    months = pd.date_range("2000-01-01", periods=12 * 10, freq="MS")
    angle = 2.0 * np.pi * (months.month.to_numpy() - 3) / 12.0
    values, weights = _matrices_from(50.0 + 20.0 * np.cos(angle), 12 * 10)

    modes = retained_modes(
        values, weights, kind="peak", min_frequency=0.60, min_separation_months=2, random_state=0
    )

    assert len(modes) == 1
    assert modes[0] == 3


def test_bimodal_record_retains_two_peaks():
    months = pd.date_range("2000-01-01", periods=12 * 12, freq="MS")
    angle = 2.0 * np.pi * (months.month.to_numpy() - 1) / 12.0
    values, weights = _matrices_from(50.0 + 20.0 * np.cos(2.0 * angle), 12 * 12)

    modes = retained_modes(
        values, weights, kind="peak", min_frequency=0.60, min_separation_months=2, random_state=0
    )

    assert len(modes) == 2


def test_close_modes_are_thinned_to_one():
    months = pd.date_range("2000-01-01", periods=12 * 10, freq="MS")
    angle = 2.0 * np.pi * (months.month.to_numpy() - 6) / 12.0
    values, weights = _matrices_from(50.0 + 20.0 * np.cos(angle), 12 * 10)

    modes = retained_modes(
        values, weights, kind="peak", min_frequency=0.10, min_separation_months=6, random_state=0
    )

    assert len(modes) == 1


def test_trough_kind_finds_the_minimum_side():
    months = pd.date_range("2000-01-01", periods=12 * 10, freq="MS")
    angle = 2.0 * np.pi * (months.month.to_numpy() - 3) / 12.0
    values, weights = _matrices_from(50.0 + 20.0 * np.cos(angle), 12 * 10)

    modes = retained_modes(
        values, weights, kind="trough", min_frequency=0.60, min_separation_months=2, random_state=0
    )

    assert modes == (9,)


def test_flat_record_retains_no_modes():
    values, weights = _matrices_from(np.full(12 * 10, 30.0), 12 * 10)

    modes = retained_modes(
        values, weights, kind="peak", min_frequency=0.60, min_separation_months=2, random_state=0
    )

    assert modes == ()


def test_mode_retention_is_deterministic():
    months = pd.date_range("2000-01-01", periods=12 * 10, freq="MS")
    angle = 2.0 * np.pi * (months.month.to_numpy() - 3) / 12.0
    values, weights = _matrices_from(50.0 + 20.0 * np.cos(angle), 12 * 10)

    first = retained_modes(
        values, weights, kind="peak", min_frequency=0.60, min_separation_months=2, random_state=9
    )
    second = retained_modes(
        values, weights, kind="peak", min_frequency=0.60, min_separation_months=2, random_state=9
    )

    assert first == second


def test_min_frequency_must_be_a_fraction():
    values, weights = _matrices_from(np.full(12 * 10, 30.0), 12 * 10)

    with pytest.raises(ValueError, match="min_frequency"):
        retained_modes(
            values, weights, kind="peak", min_frequency=1.5, min_separation_months=2, random_state=0
        )


