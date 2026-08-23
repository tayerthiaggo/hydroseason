"""Surface-water regime assessment: what kind of signal is this, and what may
be asked of it?

This module answers a question that must be settled *before* hydrological-year
detection runs: does the catchment's observed surface-water record contain a
reproducible annual cycle at all? Detectors downstream will return an answer
whether or not one exists, so the gate belongs here.

Scope note, deliberately narrow: ``extent_pct`` measures **observed surface
water**, which is water availability as seen from above. It is not a climate
variable and must not be read as one. Regulation, diversion, extraction,
farm-dam storage and land-use change all move surface-water extent
independently of rainfall, so a flat or shifted signal is evidence about water
*availability*, never directly about climate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from ._boundary import RobustBoundaryConfig
from ._boundary_recoverability import (
    RecoverabilityThresholds,
)
from ._challenger import (
    ChallengerAssessment,
    assess_challenger,
    failed_challenger,
)
from ._circular_timing import (
    AnnualTimingSummary,
    CircularTimingSummary,
    summarise_circular_months,
)
from ._decision_policy import (
    ESTABLISHED_POLICY,
    REGIME_THRESHOLDS,
    DecisionPolicy,
    EstablishedDecision,
    Regime,
    Route,
    decide_established,
)
from ._events import extract_water_events
from ._evidence import (
    EvidenceThresholds,
)
from ._scientific_defaults import (
    EVIDENCE_DEFAULTS,
    RECOVERABILITY_DEFAULTS,
)
from ._state_input import QualityPolicy, prepare_monthly_extent

_DEFAULT_MIN_MONTHS_PER_YEAR = 9
_MIN_USABLE_YEARS = 5
_DRIFT_MIN_TIMING_YEARS = 10


_SCOPE_CAVEAT = (
    "extent_pct measures observed surface water (water availability), not "
    "rainfall and not a climate variable"
)
_DRIVER_CAVEAT = (
    "river regulation, extraction, diversion and land-use change move "
    "surface-water extent independently of rainfall, so regime here describes "
    "the catchment as observed, not its natural condition"
)


@dataclass(frozen=True)
class WaterRegimeAssessment:
    """What the record supports, and what it does not."""

    regime: Regime
    amplitude_snr: float
    peak_phase_iqr_months: float | None
    peak_timing_concentration: float | None
    peak_timing_concentration_ci_low: float | None
    peak_timing_concentration_ci_high: float | None
    peak_timing_uniformity_p: float | None
    trough_phase_iqr_months: float | None
    trough_timing_concentration: float | None
    trough_timing_concentration_ci_low: float | None
    trough_timing_concentration_ci_high: float | None
    trough_timing_uniformity_p: float | None
    n_timing_years: int
    climatological_peak_month: int | None
    climatological_trough_month: int | None
    n_usable_years: int
    n_usable_months: int
    n_wet_events: int
    longest_low_spell_months: int
    years_without_wet_event: int
    recommended_action: str
    caveats: tuple[str, ...]

    decision_policy: DecisionPolicy = ESTABLISHED_POLICY
    public_route: Route = "insufficient_record"
    challenger: ChallengerAssessment = field(default_factory=ChallengerAssessment)

    @property
    def supports_per_year_boundaries(self) -> bool:
        """Whether public hydrological years may be published for this record."""
        return self.public_route == "per_year_detection"

    @property
    def attempts_per_year_detection(self) -> bool:
        """Whether the detector runs at all, as an internal diagnostic."""
        return self.regime in {"seasonal", "marginal"}

    @property
    def supports_fixed_window(self) -> bool:
        """Whether one fixed climatological wet/dry window is defensible.

        Seasonal records always support a fixed window. Marginal records
        require concentrated, non-uniform peak and trough timings.
        """
        return self.public_route in {"per_year_detection", "fixed_climatological_window"}

    # 0.2.0 Compatibility properties forwarding to self.challenger:
    @property
    def seasonal_amplitude_pp(self) -> float:
        return self.challenger.seasonal_amplitude_pp

    @property
    def amplitude_noise_ratio(self) -> float:
        return self.challenger.amplitude_noise_ratio

    @property
    def seasonal_cv_skill(self) -> float:
        return self.challenger.seasonal_cv_skill

    @property
    def periodicity_p(self) -> float:
        return self.challenger.periodicity_p

    @property
    def selected_harmonic_order(self) -> int:
        return self.challenger.selected_harmonic_order

    @property
    def peak_timing(self) -> AnnualTimingSummary | None:
        return self.challenger.peak_timing

    @property
    def trough_timing(self) -> AnnualTimingSummary | None:
        return self.challenger.trough_timing

    @property
    def peak_timing_n_modes(self) -> int:
        return self.challenger.peak_timing_n_modes

    @property
    def trough_timing_n_modes(self) -> int:
        return self.challenger.trough_timing_n_modes

    @property
    def peak_timing_drift_months_per_decade(self) -> float | None:
        return self.challenger.peak_timing_drift_months_per_decade

    @property
    def trough_timing_drift_months_per_decade(self) -> float | None:
        return self.challenger.trough_timing_drift_months_per_decade

    @property
    def peak_timing_drift_status(self) -> str:
        return self.challenger.peak_timing_drift_status

    @property
    def trough_timing_drift_status(self) -> str:
        return self.challenger.trough_timing_drift_status

    @property
    def annual_cycle_evidence(self) -> str:
        return self.challenger.annual_cycle_evidence

    @property
    def boundary_cv_n(self) -> int:
        return self.challenger.boundary_cv_n

    @property
    def boundary_cv_coverage(self) -> float:
        return self.challenger.boundary_cv_coverage

    @property
    def boundary_cv_within_1_month(self) -> float:
        return self.challenger.boundary_cv_within_1_month

    @property
    def boundary_cv_within_1_month_wilson_low(self) -> float:
        return self.challenger.boundary_cv_within_1_month_wilson_low

    @property
    def boundary_cv_p90_error_months(self) -> float:
        return self.challenger.boundary_cv_p90_error_months

    @property
    def boundary_recoverability(self) -> str:
        return self.challenger.boundary_recoverability

    @property
    def boundary_recoverability_reason(self) -> str:
        return self.challenger.boundary_recoverability_reason


_ACTIONS: dict[Regime, str] = {
    "seasonal": (
        "Run per-year hydrological-year detection. Peak and trough months are "
        "reproducible year to year."
    ),
    "marginal": (
        "Do not report per-year peak/trough: individual years disagree on "
        "timing. A single fixed climatological window may be applied as an "
        "explicit average-behaviour frame, recorded as an imposed assumption "
        "rather than a detected boundary. Report event descriptors alongside it."
    ),
    "aseasonal": (
        "Do not define a hydrological year. No reproducible annual cycle is "
        "present, so any peak, trough or wet/dry split would describe noise. "
        "Characterise this catchment by wet events and low-extent spell length instead."
    ),
    "insufficient_record": (
        "Too few usable years to assess regime. Extend the record or relax the "
        "quality screen; do not infer absence of seasonality from absence of data."
    ),
}


def assess_water_regime(
    extent,
    *,
    value_col: str = "extent_pct",
    date_col: str | None = None,
    min_months_per_year: int = _DEFAULT_MIN_MONTHS_PER_YEAR,
    max_invalid_pct: float = 20.0,
    quality_policy: QualityPolicy = "flag",
    measurement_tolerance_pct: float = 1.0,
    n_bootstrap: int = 200,
    random_state: int = 0,
    evidence_thresholds: EvidenceThresholds = EVIDENCE_DEFAULTS,
    recoverability_thresholds: RecoverabilityThresholds = RECOVERABILITY_DEFAULTS,
    robust_boundary_config: RobustBoundaryConfig | None = None,
    trough_search_radius_months: int = 3,
) -> WaterRegimeAssessment:
    """Assess what the observed surface-water record supports."""
    if not 1 <= min_months_per_year <= 12:
        raise ValueError("min_months_per_year must be between 1 and 12.")

    if evidence_thresholds is None:
        evidence_thresholds = EVIDENCE_DEFAULTS
    if recoverability_thresholds is None:
        recoverability_thresholds = RECOVERABILITY_DEFAULTS

    prepared = prepare_monthly_extent(
        extent,
        value_col=value_col,
        date_col=date_col,
        max_invalid_pct=max_invalid_pct,
        quality_policy=quality_policy,
    )
    usable = prepared.loc[prepared["candidate_usable"]]
    caveats = [_SCOPE_CAVEAT, _DRIVER_CAVEAT]

    qualifying_groups = [
        (int(year), group)
        for year, group in usable.groupby(usable.index.year)
        if len(set(group.index.month)) >= min_months_per_year
    ]
    qualifying_years = [year for year, _ in qualifying_groups]
    sample = usable.loc[usable.index.year.isin(qualifying_years)]

    if len(qualifying_years) < _MIN_USABLE_YEARS:
        climatology = pd.Series(dtype=float)
        snr = 0.0
        peak_timing = CircularTimingSummary(None, None, None, None, None, 0)
        trough_timing = CircularTimingSummary(None, None, None, None, None, 0)
    else:
        by_month = sample[value_col].groupby(sample.index.month)
        climatology = by_month.mean()
        amplitude = float(climatology.max() - climatology.min())
        within_month_sd = (
            float(by_month.std().mean()) if len(qualifying_years) > 1 else 0.0
        )
        if amplitude == 0.0:
            snr = 0.0
        elif within_month_sd > 0.0:
            snr = amplitude / within_month_sd
        else:
            snr = np.inf
        per_year_peaks = [int(group[value_col].idxmax().month) for _, group in qualifying_groups]
        per_year_troughs = [int(group[value_col].idxmin().month) for _, group in qualifying_groups]
        peak_timing = summarise_circular_months(
            per_year_peaks,
            n_resamples=n_bootstrap,
            random_state=random_state,
        )
        trough_timing = summarise_circular_months(
            per_year_troughs,
            n_resamples=n_bootstrap,
            random_state=random_state,
        )

    decision = decide_established(
        n_usable_years=len(qualifying_years),
        amplitude_snr=float(snr),
        peak_timing=peak_timing,
        trough_timing=trough_timing,
    )

    if decision.regime in ("seasonal", "marginal") and not climatology.empty:
        climatological_peak_month = int(climatology.idxmax())
        climatological_trough_month = int(climatology.idxmin())
    else:
        climatological_peak_month = climatological_trough_month = None

    try:
        challenger = assess_challenger(
            prepared,
            value_col=value_col,
            qualifying_years=qualifying_years,
            min_months_per_year=min_months_per_year,
            measurement_tolerance_pct=measurement_tolerance_pct,
            n_bootstrap=n_bootstrap,
            random_state=random_state,
            evidence_thresholds=evidence_thresholds,
            recoverability_thresholds=recoverability_thresholds,
            robust_boundary_config=robust_boundary_config,
            trough_search_radius_months=trough_search_radius_months,
            established_regime=decision.regime,
            established_route=decision.route,
            quality_policy=quality_policy,
        )
    except Exception as exc:
        challenger = failed_challenger(exc)
        caveats.append(f"experimental challenger failed: {challenger.error}")

    # Events extraction
    event_summary = extract_water_events(
        extent,
        value_col=value_col,
        date_col=date_col,
        max_invalid_pct=max_invalid_pct,
        quality_policy=quality_policy,
    ).summary
    n_wet_events = int(event_summary["n_events"])
    longest_low = int(event_summary["longest_low_spell_months"])
    years_without = int(event_summary["years_without_event"])

    if _MIN_USABLE_YEARS <= peak_timing.n < REGIME_THRESHOLDS["timing_record_caution_years"]:
        caveats.append(
            "fewer than 30 usable annual timings: classification is retained, "
            "but uncertainty intervals may be wide"
        )
    if (
        _MIN_USABLE_YEARS <= peak_timing.n < REGIME_THRESHOLDS["uniformity_min_timing_years"]
        and snr >= REGIME_THRESHOLDS["seasonal_min_snr"]
        and peak_timing.ci_low is not None
        and peak_timing.ci_low < REGIME_THRESHOLDS["strong_timing_concentration"]
        and peak_timing.uniformity_p is not None
        and peak_timing.uniformity_p >= REGIME_THRESHOLDS["circular_uniformity_alpha"]
    ):
        caveats.append(
            "the circular-uniformity result has little power with fewer than "
            "10 annual timings, so the record remains marginal"
        )
    if decision.regime == "marginal":
        caveats.append(
            "peak-timing concentration does not provide strong enough evidence "
            "for per-year boundaries, so the climatological peak describes "
            "average behaviour only"
        )
    if decision.regime == "aseasonal":
        caveats.append(
            "no reproducible annual cycle: peak and trough are withheld because "
            "any value would reflect noise rather than a seasonal signal"
        )
    if years_without:
        caveats.append(
            f"{years_without} of {len(qualifying_groups)} usable years contain no "
            f"wet event above {max_invalid_pct:.0f}% invalid ceiling"
        )

    return WaterRegimeAssessment(
        regime=decision.regime,
        amplitude_snr=float(snr),
        peak_phase_iqr_months=peak_timing.iqr_months,
        peak_timing_concentration=peak_timing.concentration,
        peak_timing_concentration_ci_low=peak_timing.ci_low,
        peak_timing_concentration_ci_high=peak_timing.ci_high,
        peak_timing_uniformity_p=peak_timing.uniformity_p,
        trough_phase_iqr_months=trough_timing.iqr_months,
        trough_timing_concentration=trough_timing.concentration,
        trough_timing_concentration_ci_low=trough_timing.ci_low,
        trough_timing_concentration_ci_high=trough_timing.ci_high,
        trough_timing_uniformity_p=trough_timing.uniformity_p,
        n_timing_years=peak_timing.n,
        climatological_peak_month=climatological_peak_month,
        climatological_trough_month=climatological_trough_month,
        n_usable_years=len(qualifying_years),
        n_usable_months=int(len(usable)),
        n_wet_events=n_wet_events,
        longest_low_spell_months=longest_low,
        years_without_wet_event=years_without,
        recommended_action=_ACTIONS[decision.regime],
        caveats=tuple(caveats),
        decision_policy=decision.policy,
        public_route=decision.route,
        challenger=challenger,
    )


PublicRoute = Literal[
    "per_year_detection", "event_characterisation", "insufficient_record"
]


def public_route(regime: Regime, recoverability: str) -> PublicRoute:
    """Map regime and boundary recoverability to the public route (legacy 0.2.0 diagnostic mapping)."""
    if regime == "insufficient_record":
        return "insufficient_record"
    if regime in {"seasonal", "marginal"} and recoverability == "supported":
        return "per_year_detection"
    return "event_characterisation"


__all__ = [
    "DecisionPolicy",
    "ESTABLISHED_POLICY",
    "EstablishedDecision",
    "PublicRoute",
    "REGIME_THRESHOLDS",
    "Regime",
    "Route",
    "WaterRegimeAssessment",
    "assess_water_regime",
    "decide_established",
    "public_route",
]
