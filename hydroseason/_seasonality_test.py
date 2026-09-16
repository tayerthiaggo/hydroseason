"""Seasonality as recurrence of annual timing, measured on a detrended record.

The question this module answers is not how much surface water varies inside a
year, but whether its annual high and low come back at the same time of year.
Magnitude belongs to the detectability rule; recurrence is what an annual
boundary scheme actually presupposes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from ._boundary import robust_scale
from ._circular_timing import (
    AnnualTimingSummary,
    equivalent_extremum_months,
    summarise_annual_timing,
)
from ._timing_identifiability import (
    COUNT_COLUMNS,
    TimingIdentifiabilityThresholds,
    _validate_tolerance,
    annual_detectability,
)

_TREND_HALF_WINDOW = 6
_TREND_WEIGHTS = np.r_[0.5, np.ones(11), 0.5] / 12.0

TIMING_RECURRENCE_ALPHA = 0.05

_EMPTY_SUMMARY = AnnualTimingSummary(None, None, None, None, None, 0, None)


@dataclass(frozen=True)
class TrendEstimate:
    """Centred 2x12 trend, the series it leaves behind, and what was filled."""

    trend: pd.Series
    detrended: pd.Series
    interpolated: pd.Series
    n_interpolated_months: int
    n_months_without_trend: int

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TrendEstimate):
            return False
        return (
            self.trend.equals(other.trend)
            and self.detrended.equals(other.detrended)
            and self.interpolated.equals(other.interpolated)
            and self.n_interpolated_months == other.n_interpolated_months
            and self.n_months_without_trend == other.n_months_without_trend
        )


@dataclass(frozen=True)
class TimingRecurrenceResult:
    """Whether annual peak and trough timing recur on the calendar."""

    classification: Literal["seasonal", "aseasonal"] | None
    status: Literal["ok", "insufficient_record"]
    reason: str
    alpha: float
    peak: AnnualTimingSummary
    trough: AnnualTimingSummary
    peak_month_sets: dict[int, tuple[int, ...]]
    trough_month_sets: dict[int, tuple[int, ...]]
    n_qualifying_years: int
    n_timing_eligible_years: int
    n_detectable_years: int
    trend: TrendEstimate


def classical_trend(prepared: pd.DataFrame, *, value_col: str = "extent_pct") -> TrendEstimate:
    """Estimate the trend-cycle with the classical additive 2x12 moving average.

    Internal missing months are interpolated to feed the moving average only:
    an interpolated month never contributes timing evidence, because it is not
    an observation. The first and last six months have no centred window and
    therefore no trend.
    """
    if prepared.empty:
        empty_index = pd.DatetimeIndex([])
        empty = pd.Series(dtype=float, index=empty_index)
        return TrendEstimate(
            empty, empty, pd.Series(dtype=bool, index=empty_index), 0, 0
        )

    if prepared.index.has_duplicates:
        prepared = prepared.loc[~prepared.index.duplicated(keep="first")]

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


def _insufficient(
    reason: str, trend: TrendEstimate, *, alpha: float, n_qualifying: int, n_eligible: int
) -> TimingRecurrenceResult:
    return TimingRecurrenceResult(
        classification=None,
        status="insufficient_record",
        reason=reason,
        alpha=alpha,
        peak=_EMPTY_SUMMARY,
        trough=_EMPTY_SUMMARY,
        peak_month_sets={},
        trough_month_sets={},
        n_qualifying_years=n_qualifying,
        n_timing_eligible_years=n_eligible,
        n_detectable_years=0,
        trend=trend,
    )


def assess_timing_recurrence(
    prepared: pd.DataFrame,
    *,
    thresholds: TimingIdentifiabilityThresholds,
    value_col: str = "extent_pct",
    measurement_tolerance_pct: float = 0.0,
    min_months_per_year: int = 9,
    min_years: int = 5,
    alpha: float = TIMING_RECURRENCE_ALPHA,
    n_bootstrap: int = 200,
    random_state: int = 0,
) -> TimingRecurrenceResult:
    """Test whether annual extremum timing recurs on the calendar.

    Detectability is judged on raw observed extent, so the calibrated rule is
    unchanged. Month sets are read off the detrended series, with the tie
    tolerance widened by the year's trend range: every month tied in raw extent
    stays tied, so detrending cannot manufacture timing precision.
    """
    measurement_tolerance_pp = _validate_tolerance(measurement_tolerance_pct)
    trend = classical_trend(prepared, value_col=value_col)
    if prepared.empty:
        return _insufficient(
            "too_few_qualifying_years", trend, alpha=alpha, n_qualifying=0, n_eligible=0
        )

    usable = prepared.loc[prepared["candidate_usable"]]
    qualifying_years = [
        int(year)
        for year, group in usable.groupby(usable.index.year)
        if len(set(group.index.month)) >= min_months_per_year
    ]
    if len(qualifying_years) < min_years:
        return _insufficient(
            "too_few_qualifying_years",
            trend,
            alpha=alpha,
            n_qualifying=len(qualifying_years),
            n_eligible=0,
        )

    detrended = trend.detrended.dropna()
    eligible: dict[int, pd.Series] = {}
    for year in qualifying_years:
        year_values = detrended.loc[detrended.index.year == year]
        if len(year_values) >= min_months_per_year:
            eligible[year] = year_values
    if len(eligible) < min_years:
        return _insufficient(
            "trend_unavailable",
            trend,
            alpha=alpha,
            n_qualifying=len(qualifying_years),
            n_eligible=len(eligible),
        )

    _amplitude_pp, noise_pp = robust_scale(prepared)
    pixel_support_status = (
        "available" if COUNT_COLUMNS.issubset(prepared.columns) else "unavailable"
    )

    peak_month_sets: dict[int, tuple[int, ...]] = {}
    trough_month_sets: dict[int, tuple[int, ...]] = {}
    for year, year_values in eligible.items():
        rows = prepared.loc[year_values.index]
        raw_values = rows[value_col].astype(float)
        detectability = annual_detectability(
            raw_values,
            rows,
            thresholds=thresholds,
            measurement_tolerance_pp=measurement_tolerance_pp,
            noise_pp=noise_pp,
            pixel_support_status=pixel_support_status,
        )
        if not detectability.detectable:
            continue
        year_trend = trend.trend.loc[year_values.index]
        trend_range_pp = float(year_trend.max() - year_trend.min())
        tolerance = detectability.detectability_floor_pp + trend_range_pp
        peak_month_sets[year] = equivalent_extremum_months(
            year_values, kind="max", tolerance=tolerance
        )
        trough_month_sets[year] = equivalent_extremum_months(
            year_values, kind="min", tolerance=tolerance
        )

    if not peak_month_sets:
        return TimingRecurrenceResult(
            classification="aseasonal",
            status="ok",
            reason="no_detectable_years",
            alpha=alpha,
            peak=_EMPTY_SUMMARY,
            trough=_EMPTY_SUMMARY,
            peak_month_sets={},
            trough_month_sets={},
            n_qualifying_years=len(qualifying_years),
            n_timing_eligible_years=len(eligible),
            n_detectable_years=0,
            trend=trend,
        )

    from ._method_policy import CURRENT_METHOD_POLICY

    if len(peak_month_sets) < CURRENT_METHOD_POLICY.min_detectable_years:
        return TimingRecurrenceResult(
            classification="aseasonal",
            status="ok",
            reason="too_few_detectable_years",
            alpha=alpha,
            peak=_EMPTY_SUMMARY,
            trough=_EMPTY_SUMMARY,
            peak_month_sets=peak_month_sets,
            trough_month_sets=trough_month_sets,
            n_qualifying_years=len(qualifying_years),
            n_timing_eligible_years=len(eligible),
            n_detectable_years=len(peak_month_sets),
            trend=trend,
        )


    peak = summarise_annual_timing(
        peak_month_sets, n_resamples=n_bootstrap, random_state=random_state
    )
    trough = summarise_annual_timing(
        trough_month_sets, n_resamples=n_bootstrap, random_state=random_state
    )
    peak_rejects = peak.uniformity_p is not None and peak.uniformity_p < alpha
    trough_rejects = trough.uniformity_p is not None and trough.uniformity_p < alpha
    if peak_rejects and trough_rejects:
        classification, reason = "seasonal", "peak_and_trough_recur"
    elif trough_rejects:
        classification, reason = "aseasonal", "peak_uniformity_not_rejected"
    elif peak_rejects:
        classification, reason = "aseasonal", "trough_uniformity_not_rejected"
    else:
        classification, reason = "aseasonal", "peak_and_trough_uniformity_not_rejected"

    return TimingRecurrenceResult(
        classification=classification,
        status="ok",
        reason=reason,
        alpha=alpha,
        peak=peak,
        trough=trough,
        peak_month_sets=peak_month_sets,
        trough_month_sets=trough_month_sets,
        n_qualifying_years=len(qualifying_years),
        n_timing_eligible_years=len(eligible),
        n_detectable_years=len(peak_month_sets),
        trend=trend,
    )
