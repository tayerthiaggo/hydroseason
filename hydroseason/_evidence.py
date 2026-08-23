"""Shared evidence synthesis: interval estimation and categorical evidence.

Lives apart from ``_regime`` and ``_boundary_recoverability`` because both
consume it, and because Plan 4's calibration harness scores the same functions
the runtime uses rather than a reimplementation of them.
"""
from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral
from typing import TYPE_CHECKING, Literal

import numpy as np
import pandas as pd

from ._circular_timing import equivalent_extremum_months

if TYPE_CHECKING:
    from ._circular_timing import AnnualTimingSummary

# Two-sided normal quantile at 95%. Hard-coded because it is the default and
# because a lookup avoids the approximation error below for the common case.
_Z_95 = 1.959963984540054


def _normal_quantile(probability: float) -> float:
    """Two-sided normal quantile without SciPy.

    Acklam's rational approximation; absolute error below 1.15e-9 across the
    open unit interval, which is far tighter than any threshold this feeds.
    """
    tail = (1.0 - probability) / 2.0
    p = 1.0 - tail
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]
    low, high = 0.02425, 1.0 - 0.02425
    if p < low:
        q = np.sqrt(-2.0 * np.log(p))
        return float(
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        )
    if p > high:
        q = np.sqrt(-2.0 * np.log(1.0 - p))
        return float(
            -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        )
    q = p - 0.5
    r = q * q
    return float(
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    )


def wilson_interval(
    successes: int,
    trials: int,
    *,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Used instead of the normal approximation because the promotion gate runs at
    five to ten trials and at rates near one, where the normal interval is both
    too narrow and capable of leaving the unit interval.
    """
    for name, value in (("successes", successes), ("trials", trials)):
        if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer.")
    if successes > trials:
        raise ValueError("successes must not exceed trials.")
    if not 0.0 < float(confidence) < 1.0:
        raise ValueError("confidence must be between 0 and 1.")
    if trials == 0:
        return 0.0, 1.0

    z = (
        _Z_95
        if abs(float(confidence) - 0.95) < 1e-12
        else _normal_quantile(float(confidence))
    )
    n = float(trials)
    proportion = successes / n
    denominator = 1.0 + z**2 / n
    centre = (proportion + z**2 / (2.0 * n)) / denominator
    half_width = (z / denominator) * np.sqrt(
        proportion * (1.0 - proportion) / n + z**2 / (4.0 * n**2)
    )
    return float(max(0.0, centre - half_width)), float(min(1.0, centre + half_width))


def annual_extremum_month_sets(
    prepared: pd.DataFrame,
    *,
    kind: Literal["min", "max"],
    tolerance_pct: float,
) -> dict[int, tuple[int, ...]]:
    """Per-year equivalent extremum months, keyed by calendar year.

    Replaces ``idxmin``/``idxmax`` over each year, which answer a tied year by
    returning its first row and so report January for any flat record. Years
    with no usable observation are omitted rather than mapped to an empty
    tuple, so the mapping's length is the number of years carrying timing.
    """
    usable = prepared.loc[
        prepared["candidate_usable"].to_numpy(dtype=bool), "extent_pct"
    ]
    usable = usable.loc[usable.notna()]
    if usable.empty:
        return {}

    month_sets: dict[int, tuple[int, ...]] = {}
    for year, group in usable.groupby(pd.DatetimeIndex(usable.index).year):
        months = equivalent_extremum_months(
            group, kind=kind, tolerance=float(tolerance_pct)
        )
        if months:
            month_sets[int(year)] = months
    return month_sets


# The spec fixes this; it is not a tuned cutoff.
_MIN_EVALUABLE_YEARS = 5

AnnualCycleEvidence = Literal["strong", "moderate", "weak", "absent", "insufficient"]


@dataclass(frozen=True)
class EvidenceThresholds:
    """Calibrated cutoffs, supplied together so none can drift out of step.

    Deliberately without defaults. Plan 4's calibration generates every field;
    a default value here would be a tuned constant living in source, which is
    exactly what the calibration discipline exists to prevent.
    """

    seasonal_cv_skill: float
    periodicity_alpha: float
    amplitude_noise_ratio: float
    mode_min_frequency: float
    mode_min_separation_months: int
    strong_timing_concentration: float
    weak_timing_concentration: float
    min_timing_years: int

    def __post_init__(self) -> None:
        for name in (
            "seasonal_cv_skill",
            "periodicity_alpha",
            "amplitude_noise_ratio",
            "mode_min_frequency",
            "strong_timing_concentration",
            "weak_timing_concentration",
        ):
            val = getattr(self, name)
            if (
                not isinstance(val, (int, float))
                or isinstance(val, bool)
                or not np.isfinite(val)
            ):
                raise ValueError(f"{name} must be a finite number.")

        for name in ("mode_min_separation_months", "min_timing_years"):
            val = getattr(self, name)
            if isinstance(val, bool) or not isinstance(val, Integral):
                raise ValueError(f"{name} must be an integer.")

        if not (0.0 < float(self.periodicity_alpha) < 1.0):
            raise ValueError("periodicity_alpha must be between 0 and 1 exclusive.")
        if float(self.amplitude_noise_ratio) < 0.0:
            raise ValueError("amplitude_noise_ratio must be non-negative.")
        if not (0.0 < float(self.mode_min_frequency) <= 1.0):
            raise ValueError("mode_min_frequency must be in (0, 1].")
        if not (1 <= int(self.mode_min_separation_months) <= 12):
            raise ValueError("mode_min_separation_months must be between 1 and 12.")
        if not (0.0 <= float(self.weak_timing_concentration) <= 1.0):
            raise ValueError("weak_timing_concentration must be between 0 and 1.")
        if not (0.0 <= float(self.strong_timing_concentration) <= 1.0):
            raise ValueError("strong_timing_concentration must be between 0 and 1.")
        if float(self.weak_timing_concentration) >= float(
            self.strong_timing_concentration
        ):
            raise ValueError(
                "weak_timing_concentration must be strictly less than strong_timing_concentration."
            )
        if int(self.min_timing_years) < 1:
            raise ValueError("min_timing_years must be at least 1.")


def annual_cycle_evidence(
    *,
    seasonal_cv_skill: float,
    periodicity_p: float,
    amplitude_noise_ratio: float,
    peak_n_modes: int,
    trough_n_modes: int,
    n_evaluable_years: int,
    at_or_below_floor: bool,
    timing: AnnualTimingSummary | None,
    drift_status: str,
    thresholds: EvidenceThresholds,
) -> AnnualCycleEvidence:
    """Grade calendar-aligned annual-cycle evidence.

    Ordered so that structural disqualifications are answered before any
    threshold comparison: too short is ``insufficient``, no resolvable
    amplitude is ``absent``. Only then do skill, significance and timing
    combine, and multimodality or detected drift cap the grade at ``moderate``
    because neither is compatible with one stable annual cycle.
    """
    if n_evaluable_years < _MIN_EVALUABLE_YEARS:
        return "insufficient"
    if at_or_below_floor or amplitude_noise_ratio <= 0.0:
        return "absent"

    significant = periodicity_p <= (thresholds.periodicity_alpha + 1e-6)
    skilful = seasonal_cv_skill >= thresholds.seasonal_cv_skill
    loud = amplitude_noise_ratio >= thresholds.amplitude_noise_ratio

    timing_adequate = (
        timing is not None and timing.n_years >= thresholds.min_timing_years
    )
    concentration = timing.concentration if timing_adequate else None
    concentrated = (
        concentration is not None
        and concentration >= thresholds.strong_timing_concentration
    )
    weakly_concentrated = (
        concentration is not None
        and concentration >= thresholds.weak_timing_concentration
    )

    unimodal = peak_n_modes == 1 and trough_n_modes == 1
    drifting = drift_status == "detected"

    if significant and skilful and loud and concentrated and unimodal and not drifting:
        return "strong"
    if significant and (skilful or loud) and weakly_concentrated:
        return "moderate"
    if significant or skilful:
        return "weak"
    return "absent"
