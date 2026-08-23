from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from ._boundary import RobustBoundaryConfig
from ._boundary_recoverability import (
    RecoverabilityThresholds,
    assess_boundary_recoverability,
)
from ._circular_timing import (
    AnnualTimingSummary,
    summarise_annual_timing,
    timing_drift,
)
from ._decision_policy import Regime, Route
from ._evidence import (
    EvidenceThresholds,
    annual_cycle_evidence,
    annual_extremum_month_sets,
)
from ._seasonality import classify_seasonal_pattern
from ._state_input import QualityPolicy

_DRIFT_MIN_TIMING_YEARS = 10


@dataclass(frozen=True)
class ChallengerAssessment:
    status: Literal["ok", "failed"] = "ok"
    proposed_regime: Regime | None = None
    proposed_route: Route | None = None
    agreement: bool | None = None
    disagreement_reason: str | None = None
    error: str | None = None
    seasonal_amplitude_pp: float = 0.0
    amplitude_noise_ratio: float = 0.0
    seasonal_cv_skill: float = 0.0
    periodicity_p: float = 1.0
    selected_harmonic_order: int = 0
    peak_timing: AnnualTimingSummary | None = None
    trough_timing: AnnualTimingSummary | None = None
    peak_timing_n_modes: int = 0
    trough_timing_n_modes: int = 0
    peak_timing_drift_months_per_decade: float | None = None
    trough_timing_drift_months_per_decade: float | None = None
    peak_timing_drift_status: str = "insufficient_for_drift"
    trough_timing_drift_status: str = "insufficient_for_drift"
    annual_cycle_evidence: str = "insufficient"
    boundary_cv_n: int = 0
    boundary_cv_coverage: float = 0.0
    boundary_cv_within_1_month: float = 0.0
    boundary_cv_within_1_month_wilson_low: float = 0.0
    boundary_cv_p90_error_months: float = 12.0
    boundary_recoverability: str = "insufficient"
    boundary_recoverability_reason: str = "insufficient_data"


def failed_challenger(exc: Exception) -> ChallengerAssessment:
    return ChallengerAssessment(
        status="failed",
        error=f"{type(exc).__name__}: {exc}",
    )


def _regime_from_evidence(
    evidence: str, trough_modes: int, trough_drift_status: str
) -> Regime:
    """Regime describes annual-cycle evidence, not routing permission."""
    if evidence == "insufficient":
        return "insufficient_record"
    if evidence == "absent":
        return "aseasonal"
    if (
        evidence == "strong"
        and trough_modes == 1
        and trough_drift_status != "detected"
    ):
        return "seasonal"
    return "marginal"


def assess_challenger(
    prepared: pd.DataFrame,
    *,
    value_col: str,
    qualifying_years: list[int],
    min_months_per_year: int,
    measurement_tolerance_pct: float,
    n_bootstrap: int,
    random_state: int,
    evidence_thresholds: EvidenceThresholds,
    recoverability_thresholds: RecoverabilityThresholds,
    robust_boundary_config: RobustBoundaryConfig | None,
    trough_search_radius_months: int,
    established_regime: Regime,
    established_route: Route,
    quality_policy: QualityPolicy = "flag",
) -> ChallengerAssessment:
    usable = prepared.loc[prepared["candidate_usable"]]
    sample = usable.loc[usable.index.year.isin(qualifying_years)]
    values = sample[value_col]

    if not sample.empty:
        by_month = values.groupby(values.index.month)
        climatology = by_month.mean()
        amplitude = float(climatology.max() - climatology.min())
    else:
        amplitude = 0.0

    timing_tolerance_pct = min(
        float(measurement_tolerance_pct),
        0.10 * amplitude,
    )
    peak_month_sets = annual_extremum_month_sets(
        sample, kind="max", tolerance_pct=timing_tolerance_pct
    )
    trough_month_sets = annual_extremum_month_sets(
        sample, kind="min", tolerance_pct=timing_tolerance_pct
    )
    peak_timing = summarise_annual_timing(
        peak_month_sets, n_resamples=n_bootstrap, random_state=random_state
    )
    trough_timing = summarise_annual_timing(
        trough_month_sets, n_resamples=n_bootstrap, random_state=random_state
    )

    peak_drift = timing_drift(
        peak_month_sets,
        min_timing_years=_DRIFT_MIN_TIMING_YEARS,
        random_state=random_state,
    )
    trough_drift = timing_drift(
        trough_month_sets,
        min_timing_years=_DRIFT_MIN_TIMING_YEARS,
        random_state=random_state,
    )

    # Seasonality harmonic analysis
    mode_freq = evidence_thresholds.mode_min_frequency
    mode_sep = evidence_thresholds.mode_min_separation_months
    boot_n = max(n_bootstrap, 1)

    pattern_res = classify_seasonal_pattern(
        prepared,
        resolution_floor_pp=1e-6,
        measurement_tolerance_pct=measurement_tolerance_pct,
        mode_min_frequency=mode_freq,
        mode_min_separation_months=mode_sep,
        n_bootstrap=boot_n,
        n_null=max(n_bootstrap, 99),
        random_state=random_state,
        quality_policy=quality_policy,
    )

    if len(qualifying_years) < 5:
        proposed_regime: Regime = "insufficient_record"
        proposed_route: Route = "insufficient_record"
        agreement = (
            proposed_regime == established_regime
            and proposed_route == established_route
        )
        return ChallengerAssessment(
            proposed_regime=proposed_regime,
            proposed_route=proposed_route,
            agreement=agreement,
            disagreement_reason=None if agreement else (
                f"established={established_regime}/{established_route}; "
                f"challenger={proposed_regime}/{proposed_route}"
            ),
            seasonal_amplitude_pp=pattern_res.seasonal_amplitude_pp,
            amplitude_noise_ratio=pattern_res.amplitude_noise_ratio,
            seasonal_cv_skill=pattern_res.seasonal_cv_skill,
            periodicity_p=pattern_res.periodicity_p,
            selected_harmonic_order=pattern_res.selected_harmonic_order,
            peak_timing=peak_timing,
            trough_timing=trough_timing,
            peak_timing_n_modes=pattern_res.peak_timing_n_modes,
            trough_timing_n_modes=pattern_res.trough_timing_n_modes,
            peak_timing_drift_months_per_decade=peak_drift.months_per_decade,
            trough_timing_drift_months_per_decade=trough_drift.months_per_decade,
            peak_timing_drift_status=peak_drift.status,
            trough_timing_drift_status=trough_drift.status,
            annual_cycle_evidence="insufficient",
            boundary_recoverability_reason=(
                f"{len(qualifying_years)} usable years below minimum 5"
            ),
        )

    at_or_below_floor = (
        pattern_res.seasonal_amplitude_pp <= 0.0
        or pattern_res.pattern == "low_variability"
    )
    evidence = annual_cycle_evidence(
        seasonal_cv_skill=pattern_res.seasonal_cv_skill,
        periodicity_p=pattern_res.periodicity_p,
        amplitude_noise_ratio=pattern_res.amplitude_noise_ratio,
        peak_n_modes=pattern_res.peak_timing_n_modes,
        trough_n_modes=pattern_res.trough_timing_n_modes,
        n_evaluable_years=pattern_res.n_evaluable_years,
        at_or_below_floor=at_or_below_floor,
        timing=trough_timing,
        drift_status=trough_drift.status,
        thresholds=evidence_thresholds,
    )
    proposed_regime = _regime_from_evidence(
        evidence=evidence,
        trough_modes=pattern_res.trough_timing_n_modes,
        trough_drift_status=trough_drift.status,
    )
    boundary_rec = assess_boundary_recoverability(
        prepared,
        month_sets=trough_month_sets,
        evidence=evidence,
        thresholds=recoverability_thresholds,
        drift=trough_drift,
        n_trough_modes=pattern_res.trough_timing_n_modes,
        config=robust_boundary_config or RobustBoundaryConfig(),
        search_radius_months=trough_search_radius_months,
        min_usable_months=min_months_per_year,
    )

    if proposed_regime == "insufficient_record":
        proposed_route: Route = "insufficient_record"
    elif proposed_regime in {"seasonal", "marginal"} and boundary_rec.state == "supported":
        proposed_route = "per_year_detection"
    else:
        proposed_route = "event_characterisation"

    agreement = (
        proposed_regime == established_regime
        and proposed_route == established_route
    )
    disagreement_reason = None if agreement else (
        f"established={established_regime}/{established_route}; "
        f"challenger={proposed_regime}/{proposed_route}"
    )

    return ChallengerAssessment(
        status="ok",
        proposed_regime=proposed_regime,
        proposed_route=proposed_route,
        agreement=agreement,
        disagreement_reason=disagreement_reason,
        seasonal_amplitude_pp=pattern_res.seasonal_amplitude_pp,
        amplitude_noise_ratio=pattern_res.amplitude_noise_ratio,
        seasonal_cv_skill=pattern_res.seasonal_cv_skill,
        periodicity_p=pattern_res.periodicity_p,
        selected_harmonic_order=pattern_res.selected_harmonic_order,
        peak_timing=peak_timing,
        trough_timing=trough_timing,
        peak_timing_n_modes=pattern_res.peak_timing_n_modes,
        trough_timing_n_modes=pattern_res.trough_timing_n_modes,
        peak_timing_drift_months_per_decade=peak_drift.months_per_decade,
        trough_timing_drift_months_per_decade=trough_drift.months_per_decade,
        peak_timing_drift_status=peak_drift.status,
        trough_timing_drift_status=trough_drift.status,
        annual_cycle_evidence=evidence,
        boundary_cv_n=boundary_rec.n,
        boundary_cv_coverage=boundary_rec.coverage,
        boundary_cv_within_1_month=boundary_rec.within_1_month,
        boundary_cv_within_1_month_wilson_low=boundary_rec.within_1_month_wilson_low,
        boundary_cv_p90_error_months=boundary_rec.p90_error_months,
        boundary_recoverability=boundary_rec.state,
        boundary_recoverability_reason=boundary_rec.reason,
    )
