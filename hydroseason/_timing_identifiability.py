"""Pure annual evidence for whether surface-water timing is identifiable."""
from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral, Real
from typing import Literal

import numpy as np
import pandas as pd

from ._boundary import robust_scale
from ._circular_timing import (
    equivalent_extremum_dates,
    equivalent_extremum_months,
    linear_span_months,
    shortest_circular_span,
)
from ._state_input import QualityPolicy, prepare_monthly_extent

TimingStatus = Literal["point", "interval", "unresolved"]
PixelSupportStatus = Literal["available", "unavailable"]


@dataclass(frozen=True)
class TimingIdentifiabilityThresholds:
    min_amplitude_to_floor_ratio: float
    min_peak_water_pixels: int
    max_point_span_months: int
    max_boundary_interval_months: int
    min_informative_years: int

    def __post_init__(self) -> None:
        if not isinstance(self.min_amplitude_to_floor_ratio, Real) or not np.isfinite(
            self.min_amplitude_to_floor_ratio
        ) or self.min_amplitude_to_floor_ratio < 0.0:
            raise ValueError("min_amplitude_to_floor_ratio must be finite and non-negative.")
        for name in (
            "min_peak_water_pixels",
            "max_point_span_months",
            "max_boundary_interval_months",
            "min_informative_years",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer.")
        if self.max_boundary_interval_months < self.max_point_span_months:
            raise ValueError(
                "max_boundary_interval_months must be at least max_point_span_months."
            )


@dataclass(frozen=True)
class AnnualTimingEvidence:
    year: int
    n_usable_months: int
    n_zero_months: int
    zero_month_fraction: float
    amplitude_pp: float
    detectability_floor_pp: float
    amplitude_to_floor_ratio: float
    peak_n_water: int | None
    at_or_below_floor: bool
    detectable: bool
    peak_months: tuple[int, ...]
    trough_months: tuple[int, ...]
    peak_status: TimingStatus
    trough_status: TimingStatus


@dataclass(frozen=True)
class WindowTimingEvidence:
    """Detectability evidence for one bounded window (not a calendar year).

    Shares the exact detectability formula in :func:`assess_timing_identifiability`
    (same floor, same ratio, same status thresholds) but is timestamp-native and
    non-circular, so it applies to one hydrological-year cycle's start..end span
    -- which need not align to a calendar year and must not fold repeated
    calendar months from different years onto one label.
    """

    n_usable_months: int
    amplitude_pp: float
    detectability_floor_pp: float
    amplitude_to_floor_ratio: float
    peak_n_water: int | None
    at_or_below_floor: bool
    detectable: bool
    peak_dates: tuple[pd.Timestamp, ...]
    trough_dates: tuple[pd.Timestamp, ...]
    peak_status: TimingStatus
    trough_status: TimingStatus


@dataclass(frozen=True)
class RecordTimingEvidence:
    years: dict[int, AnnualTimingEvidence]
    pixel_support_status: PixelSupportStatus
    n_zero_months: int
    zero_month_fraction: float
    n_whole_zero_years: int
    n_peak_timing_years: int
    n_trough_timing_years: int
    n_timing_years: int


def _validate_tolerance(measurement_tolerance_pct: float) -> float:
    if (
        isinstance(measurement_tolerance_pct, bool)
        or not isinstance(measurement_tolerance_pct, Real)
        or not np.isfinite(measurement_tolerance_pct)
        or measurement_tolerance_pct < 0.0
    ):
        raise ValueError("measurement_tolerance_pct must be finite and non-negative.")
    return float(measurement_tolerance_pct)


def _resolution_pp(rows: pd.DataFrame) -> float:
    if "n_valid" not in rows:
        return 0.0
    valid = pd.to_numeric(rows["n_valid"], errors="coerce")
    positive = valid.loc[np.isfinite(valid) & valid.gt(0.0)]
    return float(100.0 / positive.min()) if not positive.empty else 0.0


def _peak_water_pixels(rows: pd.DataFrame) -> int | None:
    if "n_water" not in rows:
        return None
    water = pd.to_numeric(rows["n_water"], errors="coerce")
    finite = water.loc[np.isfinite(water)]
    return int(finite.max()) if not finite.empty else None


def _timing_status(months: tuple[int, ...], thresholds: TimingIdentifiabilityThresholds) -> TimingStatus:
    span = shortest_circular_span(months)
    if span is None or span > thresholds.max_boundary_interval_months:
        return "unresolved"
    if span <= thresholds.max_point_span_months:
        return "point"
    return "interval"


def _window_status(
    dates: tuple[pd.Timestamp, ...], thresholds: TimingIdentifiabilityThresholds
) -> TimingStatus:
    span = linear_span_months(dates)
    if span is None or span > thresholds.max_boundary_interval_months:
        return "unresolved"
    if span <= thresholds.max_point_span_months:
        return "point"
    return "interval"


def assess_window_timing(
    values: pd.Series,
    rows: pd.DataFrame,
    *,
    thresholds: TimingIdentifiabilityThresholds,
    measurement_tolerance_pct: float,
    noise_pp: float,
    pixel_support_status: PixelSupportStatus,
) -> WindowTimingEvidence:
    """Assess peak/trough detectability and timing status for one bounded window.

    ``values`` is the window's usable ``extent_pct`` series (any index, not
    necessarily calendar-aligned); ``rows`` is the matching frame slice carrying
    the optional pixel-count columns. Uses the identical detectability floor and
    status thresholds as :func:`assess_timing_identifiability`, so a
    hydrological-year cycle and a calendar year are judged by the same rule.
    """
    measurement_tolerance_pp = _validate_tolerance(measurement_tolerance_pct)
    n_usable = int(len(values))
    if not n_usable:
        return WindowTimingEvidence(
            0, 0.0, 0.0, 0.0, None, True, False, (), (), "unresolved", "unresolved",
        )
    values = values.astype(float)
    maximum, minimum = float(values.max()), float(values.min())
    amplitude_pp = maximum - minimum
    peak_rows = rows.loc[values.index[values == maximum]]
    trough_rows = rows.loc[values.index[values == minimum]]
    detectability_floor_pp = max(
        measurement_tolerance_pp,
        float(noise_pp),
        _resolution_pp(peak_rows),
        _resolution_pp(trough_rows),
        float(np.finfo(float).eps),
    )
    at_or_below_floor = amplitude_pp <= detectability_floor_pp
    ratio = 0.0 if at_or_below_floor else float(amplitude_pp / detectability_floor_pp)
    peak_n_water = _peak_water_pixels(peak_rows)
    detectable = bool(
        amplitude_pp > 0.0
        and not at_or_below_floor
        and ratio >= thresholds.min_amplitude_to_floor_ratio
        and (
            pixel_support_status == "unavailable"
            or peak_n_water is not None
            and peak_n_water >= thresholds.min_peak_water_pixels
        )
    )
    if detectable:
        peak_dates = equivalent_extremum_dates(values, kind="max", tolerance=detectability_floor_pp)
        trough_dates = equivalent_extremum_dates(values, kind="min", tolerance=detectability_floor_pp)
        peak_status = _window_status(peak_dates, thresholds)
        trough_status = _window_status(trough_dates, thresholds)
    else:
        peak_dates = trough_dates = ()
        peak_status = trough_status = "unresolved"
    return WindowTimingEvidence(
        n_usable_months=n_usable,
        amplitude_pp=amplitude_pp,
        detectability_floor_pp=detectability_floor_pp,
        amplitude_to_floor_ratio=ratio,
        peak_n_water=peak_n_water,
        at_or_below_floor=at_or_below_floor,
        detectable=detectable,
        peak_dates=peak_dates,
        trough_dates=trough_dates,
        peak_status=peak_status,
        trough_status=trough_status,
    )


def assess_timing_identifiability(
    extent: pd.Series | pd.DataFrame,
    *,
    thresholds: TimingIdentifiabilityThresholds,
    value_col: str = "extent_pct",
    date_col: str | None = None,
    max_invalid_pct: float = 20.0,
    quality_policy: QualityPolicy = "flag",
    measurement_tolerance_pct: float = 1.0,
) -> RecordTimingEvidence:
    """Assess annual extrema without making a regime or route decision.

    The record-wide robust noise estimate is intentionally computed once and
    reused for every annual floor.  Exact zeroes remain observed values; their
    counts are diagnostics only and do not enter the detectability predicate.
    """
    measurement_tolerance_pp = _validate_tolerance(measurement_tolerance_pct)
    prepared = prepare_monthly_extent(
        extent,
        value_col=value_col,
        date_col=date_col,
        max_invalid_pct=max_invalid_pct,
        quality_policy=quality_policy,
    )
    _amplitude_pp, noise_pp = robust_scale(prepared)
    if not np.isfinite(noise_pp) or noise_pp < 0.0:
        raise ValueError("robust noise must be finite and non-negative.")

    count_columns = {"n_water", "n_valid", "n_invalid", "n_aoi"}
    pixel_support_status: PixelSupportStatus = (
        "available" if count_columns.issubset(prepared.columns) else "unavailable"
    )
    annual: dict[int, AnnualTimingEvidence] = {}
    for raw_year, group in prepared.groupby(prepared.index.year):
        year = int(raw_year)
        usable = group.loc[
            group["candidate_usable"]
            & np.isfinite(group["extent_pct"].to_numpy(dtype=float, na_value=np.nan))
        ]
        n_usable = int(len(usable))
        n_zero = int((usable["extent_pct"] == 0.0).sum())
        zero_fraction = float(n_zero / n_usable) if n_usable else 0.0
        if not n_usable:
            annual[year] = AnnualTimingEvidence(
                year, 0, 0, zero_fraction, 0.0, 0.0, 0.0, None, True, False,
                (), (), "unresolved", "unresolved",
            )
            continue

        values = usable["extent_pct"].astype(float)
        maximum, minimum = float(values.max()), float(values.min())
        amplitude_pp = maximum - minimum
        peak_rows = usable.loc[values == maximum]
        trough_rows = usable.loc[values == minimum]
        detectability_floor_pp = max(
            measurement_tolerance_pp,
            float(noise_pp),
            _resolution_pp(peak_rows),
            _resolution_pp(trough_rows),
            float(np.finfo(float).eps),
        )
        at_or_below_floor = amplitude_pp <= detectability_floor_pp
        ratio = (
            0.0
            if at_or_below_floor
            else float(amplitude_pp / detectability_floor_pp)
        )
        peak_n_water = _peak_water_pixels(peak_rows)
        detectable = bool(
            amplitude_pp > 0.0
            and not at_or_below_floor
            and ratio >= thresholds.min_amplitude_to_floor_ratio
            and (
                pixel_support_status == "unavailable"
                or peak_n_water is not None
                and peak_n_water >= thresholds.min_peak_water_pixels
            )
        )
        if detectable:
            peak_months = equivalent_extremum_months(
                values, kind="max", tolerance=detectability_floor_pp
            )
            trough_months = equivalent_extremum_months(
                values, kind="min", tolerance=detectability_floor_pp
            )
            peak_status = _timing_status(peak_months, thresholds)
            trough_status = _timing_status(trough_months, thresholds)
        else:
            peak_months = trough_months = ()
            peak_status = trough_status = "unresolved"
        annual[year] = AnnualTimingEvidence(
            year=year,
            n_usable_months=n_usable,
            n_zero_months=n_zero,
            zero_month_fraction=zero_fraction,
            amplitude_pp=amplitude_pp,
            detectability_floor_pp=detectability_floor_pp,
            amplitude_to_floor_ratio=ratio,
            peak_n_water=peak_n_water,
            at_or_below_floor=at_or_below_floor,
            detectable=detectable,
            peak_months=peak_months,
            trough_months=trough_months,
            peak_status=peak_status,
            trough_status=trough_status,
        )

    n_zero_months = sum(year.n_zero_months for year in annual.values())
    n_usable_months = sum(year.n_usable_months for year in annual.values())
    n_peak_timing_years = sum(year.peak_status != "unresolved" for year in annual.values())
    n_trough_timing_years = sum(year.trough_status != "unresolved" for year in annual.values())
    return RecordTimingEvidence(
        years=annual,
        pixel_support_status=pixel_support_status,
        n_zero_months=n_zero_months,
        zero_month_fraction=(float(n_zero_months / n_usable_months) if n_usable_months else 0.0),
        n_whole_zero_years=sum(
            year.n_usable_months == 12 and year.n_zero_months == 12
            for year in annual.values()
        ),
        n_peak_timing_years=n_peak_timing_years,
        n_trough_timing_years=n_trough_timing_years,
        n_timing_years=n_peak_timing_years,
    )


__all__ = [
    "AnnualTimingEvidence",
    "PixelSupportStatus",
    "RecordTimingEvidence",
    "TimingIdentifiabilityThresholds",
    "TimingStatus",
    "WindowTimingEvidence",
    "assess_timing_identifiability",
    "assess_window_timing",
]
