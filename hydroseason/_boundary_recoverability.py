"""Does a trough phase learned without a year recover that year's low water?

This is deliberately not an accuracy measure. There is no independent
real-world boundary truth, so what is measured is *reproducibility*: whether
the phase generalises across years of the same record. Plan 4's synthetic
partition is where accuracy against known truth is established.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ._boundary import RobustBoundaryConfig, robust_scale, select_window_minimum
from ._circular_timing import summarise_annual_timing

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
