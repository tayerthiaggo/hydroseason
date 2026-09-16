import numpy as np
import pandas as pd
import pytest

from hydroseason._boundary import robust_scale
from hydroseason._circular_timing import summarise_annual_timing
from hydroseason._scientific_defaults import TIMING_IDENTIFIABILITY_DEFAULTS
from hydroseason._seasonality_test import assess_timing_recurrence, classical_trend
from hydroseason._state_input import prepare_monthly_extent
from hydroseason._timing_identifiability import COUNT_COLUMNS, annual_detectability


def _frame(values, *, start="1990-01-01", invalid_pct=0.0):
    index = pd.date_range(start, periods=len(values), freq="MS")
    return pd.DataFrame(
        {"extent_pct": np.asarray(values, dtype=float), "invalid_pct": invalid_pct},
        index=index,
    )


def test_trend_removes_a_linear_ramp_exactly():
    months = np.arange(120)
    prepared = prepare_monthly_extent(_frame(10.0 + 0.2 * months))

    estimate = classical_trend(prepared)

    interior = estimate.detrended.dropna()
    assert len(interior) == 120 - 12
    assert np.allclose(interior.to_numpy(), 0.0, atol=1e-9)


def test_trend_annihilates_a_pure_annual_cycle():
    months = np.arange(120)
    prepared = prepare_monthly_extent(_frame(30.0 + 5.0 * np.cos(2 * np.pi * months / 12)))

    estimate = classical_trend(prepared)

    interior = estimate.trend.dropna()
    assert np.allclose(interior.to_numpy(), 30.0, atol=1e-9)


def test_ends_have_no_trend_and_no_detrended_value():
    prepared = prepare_monthly_extent(_frame(np.full(60, 20.0)))

    estimate = classical_trend(prepared)

    assert estimate.trend.iloc[:6].isna().all()
    assert estimate.trend.iloc[-6:].isna().all()
    assert estimate.detrended.iloc[:6].isna().all()
    assert estimate.detrended.iloc[-6:].isna().all()
    assert estimate.n_months_without_trend == 12


def test_internal_gaps_feed_the_trend_but_never_the_detrended_series():
    values = 10.0 + 0.2 * np.arange(120)
    frame = _frame(values)
    frame.loc[frame.index[40], "extent_pct"] = np.nan
    frame.loc[frame.index[40], "invalid_pct"] = 100.0
    prepared = prepare_monthly_extent(frame)

    estimate = classical_trend(prepared)

    gap = frame.index[40]
    assert estimate.interpolated.loc[gap]
    assert estimate.n_interpolated_months == 1
    assert np.isfinite(estimate.trend.loc[gap])
    assert np.isnan(estimate.detrended.loc[gap])
    assert np.isfinite(estimate.detrended.loc[frame.index[41]])


def test_classical_trend_on_an_empty_frame_returns_a_datetime_index():
    """Every non-empty path returns a DatetimeIndex; the empty-frame branch
    must match, not fall back to a default RangeIndex."""
    prepared = prepare_monthly_extent(_frame([]))
    assert prepared.empty

    estimate = classical_trend(prepared)

    assert isinstance(estimate.trend.index, pd.DatetimeIndex)
    assert isinstance(estimate.detrended.index, pd.DatetimeIndex)
    assert isinstance(estimate.interpolated.index, pd.DatetimeIndex)
    assert estimate.trend.empty
    assert estimate.detrended.empty
    assert estimate.interpolated.empty


def test_leading_and_trailing_gaps_are_not_extrapolated():
    values = np.full(60, 20.0)
    frame = _frame(values)
    for position in (0, 59):
        frame.loc[frame.index[position], "extent_pct"] = np.nan
        frame.loc[frame.index[position], "invalid_pct"] = 100.0
    prepared = prepare_monthly_extent(frame)

    estimate = classical_trend(prepared)

    assert estimate.n_interpolated_months == 0


def _assess(frame, **kwargs):
    prepared = prepare_monthly_extent(frame)
    return assess_timing_recurrence(
        prepared, thresholds=TIMING_IDENTIFIABILITY_DEFAULTS, **kwargs
    )


def _annual(years, *, amplitude=5.0, centre=50.0, slope=0.0, noise=0.0, seed=0):
    rng = np.random.default_rng(seed)
    months = np.arange(12 * years)
    values = centre + slope * months + amplitude * np.cos(2 * np.pi * months / 12)
    if noise:
        values = values + rng.normal(0.0, noise, size=len(values))
    return _frame(values)


def test_annual_cycle_with_a_trend_is_seasonal():
    # The design's counterexample: 10 + 0.2t + 5cos(2*pi*t/12), which the
    # established SNR gate calls aseasonal. Centred at 10 so 30 years of
    # +0.2/month stays inside the 0-100% extent domain (peak 86.8%).
    result = _assess(_annual(30, centre=10.0, slope=0.2))

    assert result.status == "ok"
    assert result.classification == "seasonal"
    assert result.reason == "peak_and_trough_recur"
    assert result.peak.uniformity_p < 0.05
    assert result.trough.uniformity_p < 0.05


def test_white_noise_is_aseasonal():
    rng = np.random.default_rng(3)
    result = _assess(_frame(50.0 + rng.normal(0.0, 2.5, size=360)))

    assert result.status == "ok"
    assert result.classification == "aseasonal"
    assert result.reason.endswith("uniformity_not_rejected")


def test_a_short_record_is_insufficient_not_aseasonal():
    result = _assess(_annual(4))

    assert result.status == "insufficient_record"
    assert result.reason == "too_few_qualifying_years"
    assert result.classification is None


def test_a_record_without_enough_trend_months_is_insufficient():
    # Six clean years qualify on observed months, but the centred 2x12 window
    # leaves the first and last six months without a trend, so only the four
    # interior years reach nine detrended months. Insufficiency must be
    # reported as trend_unavailable, never folded into aseasonal.
    result = _assess(_annual(6))

    assert result.status == "insufficient_record"
    assert result.reason == "trend_unavailable"
    assert result.n_qualifying_years == 6
    assert result.n_timing_eligible_years == 4


def test_a_flat_record_reports_no_detectable_years():
    result = _assess(_frame(np.full(360, 20.0)))

    assert result.status == "ok"
    assert result.classification == "aseasonal"
    assert result.reason == "no_detectable_years"
    assert result.n_detectable_years == 0


@pytest.mark.parametrize("n_detectable", [1, 2, 3, 4])
def test_one_to_four_detectable_years_do_not_establish_recurrence(n_detectable):
    values = np.full(12 * 7, 20.0)
    for offset in range(n_detectable):
        start = 12 * (1 + offset)
        values[start : start + 12] = 20.0 + 5.0 * np.cos(
            2 * np.pi * np.arange(12) / 12
        )
    result = _assess(_frame(values))
    assert result.status == "ok"
    assert result.classification == "aseasonal"
    assert result.reason == "too_few_detectable_years"
    assert result.n_detectable_years == n_detectable


def test_detrending_never_sharpens_a_zero_plateau():
    values = np.zeros(240)
    months = np.arange(240) % 12
    values[np.isin(months, [1, 2, 3])] = 30.0
    result = _assess(_frame(values))

    interior_years = sorted(result.trough_month_sets)[1:-1]
    for year in interior_years:
        assert set(result.trough_month_sets[year]) == {1, 5, 6, 7, 8, 9, 10, 11, 12}


def test_classification_is_invariant_to_calendar_rotation():
    classes = set()
    for shift in range(12):
        months = np.arange(360)
        values = 50.0 + 5.0 * np.cos(2 * np.pi * (months - shift) / 12)
        classes.add(_assess(_frame(values)).classification)

    assert classes == {"seasonal"}


def test_results_are_reproducible_for_a_fixed_seed():
    frame = _annual(20, noise=2.5, seed=11)

    first = _assess(frame, random_state=7)
    second = _assess(frame, random_state=7)

    assert first.peak.uniformity_p == second.peak.uniformity_p
    assert first.trough.uniformity_p == second.trough.uniformity_p


def test_unequal_bimodality_can_be_kuiper_significant_with_low_resultant():
    # Two antipodal modes with 3:1 prevalence are concentrated away from a
    # uniform calendar, but their first harmonic partially cancels.
    month_sets = {year: ((7,) if year % 4 == 0 else (1,)) for year in range(200)}
    summary = summarise_annual_timing(month_sets, random_state=0)

    assert summary.uniformity_p < 0.05
    assert summary.concentration is not None
    assert 0.3 <= summary.concentration <= 0.7


def test_raw_tied_months_stay_tied_after_detrending():
    """Every month tied at a year's RAW extremum must survive into the
    DETRENDED month set.

    ``assess_timing_recurrence`` computes the per-year detectability floor
    from raw extent the same way ``annual_detectability`` does (using the
    record's robust noise scale), then WIDENS that floor by the year's trend
    range before reading extremum months off the DETRENDED series -- the
    widening is exactly what is meant to absorb detrending's distortion of
    raw ties (see its docstring: "tie tolerance widened by the year's trend
    range"). So a month counts as raw-tied here using the floor alone (the
    pre-widening tolerance detectability is judged on), and must appear in
    ``trough_month_sets``, which the implementation populated using the
    widened floor + trend-range tolerance.
    """
    rng = np.random.default_rng(5)
    months = np.arange(240)
    values = 40.0 + 0.05 * months + 6.0 * np.cos(2 * np.pi * months / 12)
    values = np.round(values + rng.normal(0.0, 1.0, size=values.size), 1)
    prepared = prepare_monthly_extent(_frame(values))
    result = assess_timing_recurrence(prepared, thresholds=TIMING_IDENTIFIABILITY_DEFAULTS)

    trend = result.trend
    _amplitude_pp, noise_pp = robust_scale(prepared)
    pixel_support_status = (
        "available" if COUNT_COLUMNS.issubset(prepared.columns) else "unavailable"
    )

    n_years_checked = 0
    for year, detrended_months in result.trough_month_sets.items():
        year_values = trend.detrended.dropna()
        year_values = year_values.loc[year_values.index.year == year]
        rows = prepared.loc[year_values.index]
        raw = rows["extent_pct"].astype(float)
        detectability = annual_detectability(
            raw,
            rows,
            thresholds=TIMING_IDENTIFIABILITY_DEFAULTS,
            measurement_tolerance_pp=0.0,
            noise_pp=noise_pp,
            pixel_support_status=pixel_support_status,
        )
        raw_tied = {
            int(stamp.month)
            for stamp, value in raw.items()
            if value <= float(raw.min()) + detectability.detectability_floor_pp
        }
        assert raw_tied.issubset(set(detrended_months))
        n_years_checked += 1

    assert n_years_checked > 0


def test_zero_plateau_raw_ties_survive_detrending():
    """The case that actually exercises the tie widening.

    A nine-month exact-zero dry plateau is one raw tie. Detrending subtracts a
    trend that varies across the year, which breaks those ties and collapses
    the trough to a single month. Only the tolerance widened by the year's
    trend range restores the full raw set. A gentle-trend fixture cannot test
    this: there the trend range never exceeds the detectability floor, so
    dropping the widening changes nothing observable.
    """
    rng = np.random.default_rng(0)
    months = np.arange(240)
    values = np.zeros(240)
    wet = np.isin(months % 12, (1, 2, 3))
    values[wet] = np.clip(30.0 + rng.normal(0.0, 2.0, size=int(wet.sum())), 0.0, None)
    prepared = prepare_monthly_extent(_frame(values))
    result = assess_timing_recurrence(prepared, thresholds=TIMING_IDENTIFIABILITY_DEFAULTS)

    checked = 0
    for year, detrended_months in result.trough_month_sets.items():
        raw = prepared.loc[prepared.index.year == year, "extent_pct"].astype(float)
        zero_months = {int(stamp.month) for stamp, value in raw.items() if value == 0.0}
        if len(zero_months) < 5:
            continue
        assert zero_months.issubset(set(detrended_months)), (
            f"year {year}: raw zero-tied months {sorted(zero_months)} were not all "
            f"preserved in the detrended trough set {sorted(detrended_months)}"
        )
        checked += 1

    assert checked > 0, "fixture produced no multi-month zero plateau to check"
