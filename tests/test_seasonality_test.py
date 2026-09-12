import numpy as np
import pandas as pd

from hydroseason._seasonality_test import classical_trend
from hydroseason._state_input import prepare_monthly_extent


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


def test_leading_and_trailing_gaps_are_not_extrapolated():
    values = np.full(60, 20.0)
    frame = _frame(values)
    for position in (0, 59):
        frame.loc[frame.index[position], "extent_pct"] = np.nan
        frame.loc[frame.index[position], "invalid_pct"] = 100.0
    prepared = prepare_monthly_extent(frame)

    estimate = classical_trend(prepared)

    assert estimate.n_interpolated_months == 0
