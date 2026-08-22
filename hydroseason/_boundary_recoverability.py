"""Does a trough phase learned without a year recover that year's low water?

This is deliberately not an accuracy measure. There is no independent
real-world boundary truth, so what is measured is *reproducibility*: whether
the phase generalises across years of the same record. Plan 4's synthetic
partition is where accuracy against known truth is established.
"""
from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral
from typing import TYPE_CHECKING, Literal

import numpy as np
import pandas as pd

from ._boundary import RobustBoundaryConfig, robust_scale, select_window_minimum
from ._circular_timing import summarise_annual_timing
from ._evidence import wilson_interval

if TYPE_CHECKING:
    from ._circular_timing import TimingDrift

_MONTHS_PER_YEAR = 12


@dataclass(frozen=True)
class YearEvaluation:
    """One held-out year scored against a phase learned from the others."""

    year: int
    evaluable: bool
    resolved: bool
    error_months: float | None
    training_trough_month: int | None
    reason: str


def _circular_month_distance(left: int, right: int) -> int:
    raw = abs(left - right)
    return min(raw, _MONTHS_PER_YEAR - raw)


def _distance_to_run(month: int, run_months: tuple[int, ...]) -> float:
    """Zero inside the equivalent-low run, else distance to its nearer end.

    A flat trough has no single correct month, so landing anywhere inside the
    run is exact. Penalising the detector for choosing one tied month over
    another would measure tie-breaking, not recoverability.
    """
    if month in run_months:
        return 0.0
    return float(min(_circular_month_distance(month, other) for other in run_months))


def _interval_for_phase(
    year: int, phase_month: int
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Twelve months centred on ``phase_month`` within ``year``."""
    centre = pd.Timestamp(year=year, month=phase_month, day=1)
    start = centre - pd.DateOffset(months=_MONTHS_PER_YEAR // 2)
    return start, start + pd.DateOffset(months=_MONTHS_PER_YEAR - 1)


def evaluate_year(
    prepared: pd.DataFrame,
    *,
    year: int,
    month_sets: dict[int, tuple[int, ...]],
    config: RobustBoundaryConfig,
    search_radius_months: int,
    min_usable_months: int,
) -> YearEvaluation:
    """Score one held-out year against a trough phase learned without it."""
    training = {
        other: months for other, months in month_sets.items() if other != year
    }
    if len(training) < 2:
        return YearEvaluation(
            year, False, False, None, None, "insufficient training years"
        )

    summary = summarise_annual_timing(training, n_resamples=20, random_state=0)
    phase_month = summary.dominant_month
    if phase_month is None:
        return YearEvaluation(
            year, False, False, None, None, "training phase undefined"
        )

    start, end = _interval_for_phase(year, phase_month)
    reference_window = prepared.loc[start:end]
    usable = reference_window.loc[
        reference_window["candidate_usable"].to_numpy(dtype=bool)
    ]
    usable = usable.loc[usable["extent_pct"].notna()]
    if len(usable) < int(min_usable_months):
        return YearEvaluation(
            year,
            False,
            False,
            None,
            phase_month,
            f"only {len(usable)} usable months in interval",
        )

    amplitude_pp, noise_pp = robust_scale(prepared)
    expected = pd.Timestamp(year=year, month=phase_month, day=1)
    reference = select_window_minimum(
        reference_window,
        expected=expected,
        expected_count=_MONTHS_PER_YEAR,
        noise_pp=noise_pp,
        amplitude_pp=amplitude_pp,
        config=config,
    )
    if (
        reference.raw_month is None
        or reference.run_start is None
        or reference.run_end is None
    ):
        return YearEvaluation(
            year, False, False, None, phase_month, "no reference minimum"
        )

    reference_run = tuple(
        int(stamp.month)
        for stamp in reference_window.loc[
            reference.run_start : reference.run_end
        ].index
    )

    candidate_start = expected - pd.DateOffset(months=int(search_radius_months))
    candidate_end = expected + pd.DateOffset(months=int(search_radius_months))
    candidate_window = prepared.loc[candidate_start:candidate_end]
    candidate_count = 2 * int(search_radius_months) + 1

    selection = select_window_minimum(
        candidate_window,
        expected=expected,
        expected_count=candidate_count,
        noise_pp=noise_pp,
        amplitude_pp=amplitude_pp,
        config=config,
    )
    if selection.selected_month is None:
        return YearEvaluation(
            year, True, False, None, phase_month, "detector returned no month"
        )

    error = _distance_to_run(int(selection.selected_month.month), reference_run)
    return YearEvaluation(year, True, True, error, phase_month, "ok")


RecoverabilityState = Literal["supported", "provisional", "unsupported", "insufficient"]


@dataclass(frozen=True)
class RecoverabilityThresholds:
    """Calibrated gate for publishing hydrological years. No defaults."""

    min_years: int
    min_coverage: float
    min_within_1_month: float
    within_1_month_wilson_floor: float
    max_p90_error_months: float
    admit_insufficient_drift: bool

    def __post_init__(self) -> None:
        if (
            isinstance(self.min_years, bool)
            or not isinstance(self.min_years, Integral)
            or int(self.min_years) < 1
        ):
            raise ValueError("min_years must be an integer >= 1.")

        for name in (
            "min_coverage",
            "min_within_1_month",
            "within_1_month_wilson_floor",
            "max_p90_error_months",
        ):
            val = getattr(self, name)
            if (
                not isinstance(val, (int, float))
                or isinstance(val, bool)
                or not np.isfinite(val)
            ):
                raise ValueError(f"{name} must be a finite number.")

        for name in (
            "min_coverage",
            "min_within_1_month",
            "within_1_month_wilson_floor",
        ):
            val = float(getattr(self, name))
            if not (0.0 <= val <= 1.0):
                raise ValueError(f"{name} must be between 0 and 1.")

        if float(self.max_p90_error_months) < 0.0:
            raise ValueError("max_p90_error_months must be non-negative.")

        if not isinstance(self.admit_insufficient_drift, bool):
            raise ValueError("admit_insufficient_drift must be a boolean.")


@dataclass(frozen=True)
class BoundaryRecoverability:
    """Reproducibility of trough boundaries, with the width of its evidence."""

    n: int
    coverage: float
    within_1_month: float
    within_1_month_wilson_low: float
    p90_error_months: float
    state: RecoverabilityState
    reason: str


def assess_boundary_recoverability(
    prepared: pd.DataFrame,
    *,
    month_sets: dict[int, tuple[int, ...]],
    evidence: str,
    thresholds: RecoverabilityThresholds,
    drift: TimingDrift,
    n_trough_modes: int,
    config: RobustBoundaryConfig,
    search_radius_months: int,
    min_usable_months: int,
) -> BoundaryRecoverability:
    """Aggregate per-year evaluations into a publication gate.

    ``supported`` is the only state that authorises public hydrological years,
    so it is bounded twice: by the point estimate and by the lower Wilson bound
    of that estimate. Reporting only the point estimate would let a four-of-five
    record publish on evidence consistent with a true rate below 40%.
    """
    evaluations = [
        evaluate_year(
            prepared,
            year=year,
            month_sets=month_sets,
            config=config,
            search_radius_months=search_radius_months,
            min_usable_months=min_usable_months,
        )
        for year in sorted(month_sets)
    ]
    evaluable = [item for item in evaluations if item.evaluable]
    resolved = [
        item for item in evaluable if item.resolved and item.error_months is not None
    ]

    n = len(evaluable)
    coverage = len(resolved) / n if n else 0.0
    errors = np.asarray([item.error_months for item in resolved], dtype=float)
    within_count = int(np.count_nonzero(errors <= 1.0)) if len(errors) else 0
    within_rate = within_count / n if n else 0.0
    wilson_low, _ = wilson_interval(within_count, n) if n else (0.0, 1.0)
    p90 = float(np.percentile(errors, 90)) if len(errors) else float(_MONTHS_PER_YEAR)

    if evidence == "absent" or (n and coverage == 0.0):
        return BoundaryRecoverability(
            n,
            coverage,
            within_rate,
            wilson_low,
            p90,
            "unsupported",
            "annual-cycle evidence absent"
            if evidence == "absent"
            else "zero boundary coverage",
        )
    if n < thresholds.min_years:
        return BoundaryRecoverability(
            n,
            coverage,
            within_rate,
            wilson_low,
            p90,
            "insufficient",
            f"{n} evaluable years below minimum {thresholds.min_years}",
        )

    failures: list[str] = []
    if coverage < thresholds.min_coverage:
        failures.append(f"coverage {coverage:.2f}")
    if within_rate < thresholds.min_within_1_month:
        failures.append(f"within_1_month {within_rate:.2f}")
    if wilson_low < thresholds.within_1_month_wilson_floor:
        failures.append(f"within_1_month Wilson lower bound {wilson_low:.2f}")
    if p90 > thresholds.max_p90_error_months:
        failures.append(f"p90 error {p90:.1f} months")
    if n_trough_modes != 1:
        failures.append(f"{n_trough_modes} trough modes")
    if drift.status == "detected":
        failures.append("trough timing drift detected")
    elif (
        drift.status == "insufficient_for_drift"
        and not thresholds.admit_insufficient_drift
    ):
        failures.append("drift status insufficient_for_drift")

    if failures:
        return BoundaryRecoverability(
            n,
            coverage,
            within_rate,
            wilson_low,
            p90,
            "provisional",
            "; ".join(failures),
        )

    # Never silent: an admitted unmeasurable drift is recorded on the way past.
    reason = (
        "supported with drift status insufficient_for_drift admitted by calibration"
        if drift.status == "insufficient_for_drift"
        else "supported"
    )
    return BoundaryRecoverability(
        n, coverage, within_rate, wilson_low, p90, "supported", reason
    )
