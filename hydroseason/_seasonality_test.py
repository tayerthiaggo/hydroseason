"""Seasonality as recurrence of annual timing, measured on a detrended record.

The question this module answers is not how much surface water varies inside a
year, but whether its annual high and low come back at the same time of year.
Magnitude belongs to the detectability rule; recurrence is what an annual
boundary scheme actually presupposes.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

_TREND_WINDOW_MONTHS = 13
_TREND_HALF_WINDOW = 6
_TREND_WEIGHTS = np.r_[0.5, np.ones(11), 0.5] / 12.0


@dataclass(frozen=True)
class TrendEstimate:
    """Centred 2x12 trend, the series it leaves behind, and what was filled."""

    trend: pd.Series
    detrended: pd.Series
    interpolated: pd.Series
    n_interpolated_months: int
    n_months_without_trend: int


def classical_trend(prepared: pd.DataFrame, *, value_col: str = "extent_pct") -> TrendEstimate:
    """Estimate the trend-cycle with the classical additive 2x12 moving average.

    Internal missing months are interpolated to feed the moving average only:
    an interpolated month never contributes timing evidence, because it is not
    an observation. The first and last six months have no centred window and
    therefore no trend.
    """
    if prepared.empty:
        empty = pd.Series(dtype=float)
        return TrendEstimate(empty, empty, pd.Series(dtype=bool), 0, 0)

    grid = pd.date_range(prepared.index.min(), prepared.index.max(), freq="MS")
    usable = prepared["candidate_usable"].to_numpy(dtype=bool)
    observed = prepared[value_col].astype(float).where(usable).reindex(grid)
    filled = observed.interpolate(method="time", limit_area="inside")
    interpolated = filled.notna() & observed.isna()

    values = filled.to_numpy(dtype=float)
    trend = np.full(len(values), np.nan)
    for position in range(_TREND_HALF_WINDOW, len(values) - _TREND_HALF_WINDOW):
        window = values[position - _TREND_HALF_WINDOW : position + _TREND_HALF_WINDOW + 1]
        if np.isfinite(window).all():
            trend[position] = float(np.dot(_TREND_WEIGHTS, window))

    trend_series = pd.Series(trend, index=grid, name="trend")
    detrended = (observed - trend_series).rename("detrended")
    return TrendEstimate(
        trend=trend_series,
        detrended=detrended,
        interpolated=interpolated,
        n_interpolated_months=int(interpolated.sum()),
        n_months_without_trend=int(trend_series.isna().sum()),
    )
