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

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from ._boundary import RobustBoundaryConfig
from ._boundary_recoverability import (
    BoundaryRecoverability,
    RecoverabilityThresholds,
    assess_boundary_recoverability,
)
from ._circular_timing import (
    CircularTimingSummary,
    summarise_annual_timing,
    summarise_circular_months,
    timing_drift,
)
from ._events import extract_water_events
from ._evidence import (
    EvidenceThresholds,
    annual_cycle_evidence,
    annual_extremum_month_sets,
)
from ._seasonality import classify_seasonal_pattern
from ._state_input import QualityPolicy, prepare_monthly_extent

Regime = Literal["seasonal", "marginal", "aseasonal", "insufficient_record"]

_DEFAULT_MIN_MONTHS_PER_YEAR = 9
_MIN_USABLE_YEARS = 5

_SEASONAL_MIN_SNR = 2.0
_ASEASONAL_MAX_SNR = 0.7
_STRONG_TIMING_CONCENTRATION = 0.7
_WEAK_TIMING_CONCENTRATION = 0.3
_CIRCULAR_UNIFORMITY_ALPHA = 0.1
_UNIFORMITY_MIN_TIMING_YEARS = 10.0
_TIMING_RECORD_CAUTION_YEARS = 30.0

REGIME_THRESHOLDS: dict[str, float] = {
    "seasonal_min_snr": _SEASONAL_MIN_SNR,
    "strong_timing_concentration": _STRONG_TIMING_CONCENTRATION,
    "weak_timing_concentration": _WEAK_TIMING_CONCENTRATION,
    "aseasonal_max_snr": _ASEASONAL_MAX_SNR,
    "circular_uniformity_alpha": _CIRCULAR_UNIFORMITY_ALPHA,
    "uniformity_min_timing_years": _UNIFORMITY_MIN_TIMING_YEARS,
    "timing_record_caution_years": _TIMING_RECORD_CAUTION_YEARS,
}

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

    # 0.2.0 Evidence and recoverability additions (in spec order):
    seasonal_amplitude_pp: float = 0.0
    amplitude_noise_ratio: float = 0.0
    seasonal_cv_skill: float = 0.0
    periodicity_p: float = 1.0
    selected_harmonic_order: int = 1
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
    boundary_recoverability_reason: str = "calibration defaults not installed"

    @property
    def supports_per_year_boundaries(self) -> bool:
        """Whether public hydrological years may be published for this record."""
        return self.boundary_recoverability == "supported"

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
        if self.regime == "seasonal":
            return True
        if self.regime != "marginal":
            return False
        timing_values = (
            self.peak_timing_uniformity_p,
            self.trough_timing_uniformity_p,
            self.peak_timing_concentration,
            self.trough_timing_concentration,
        )
        return (
            all(value is not None for value in timing_values)
            and self.peak_timing_uniformity_p < _CIRCULAR_UNIFORMITY_ALPHA
            and self.trough_timing_uniformity_p < _CIRCULAR_UNIFORMITY_ALPHA
            and self.peak_timing_concentration >= _WEAK_TIMING_CONCENTRATION
            and self.trough_timing_concentration >= _WEAK_TIMING_CONCENTRATION
        )


def _classify_legacy(snr: float, peak: CircularTimingSummary) -> Regime:
    if (
        snr >= _SEASONAL_MIN_SNR
        and peak.ci_low is not None
        and peak.ci_low >= _STRONG_TIMING_CONCENTRATION
    ):
        return "seasonal"
    if snr < _ASEASONAL_MAX_SNR:
        return "aseasonal"
    if (
        peak.uniformity_p is not None
        and peak.uniformity_p >= _CIRCULAR_UNIFORMITY_ALPHA
        and peak.n >= _UNIFORMITY_MIN_TIMING_YEARS
    ):
        return "aseasonal"
    return "marginal"


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
    evidence_thresholds: EvidenceThresholds | None = None,
    recoverability_thresholds: RecoverabilityThresholds | None = None,
    robust_boundary_config: RobustBoundaryConfig | None = None,
    trough_search_radius_months: int = 3,
) -> WaterRegimeAssessment:
    """Assess what the observed surface-water record supports.

    Call this before hydrological-year detection and surface the result to the
    user. Detectors downstream cannot themselves tell a weak cycle from none,
    and their confidence grades are computed relative to the same weak signal,
    so a record with no cycle can otherwise be reported back as many
    high-confidence years.
    """
    if not 1 <= min_months_per_year <= 12:
        raise ValueError("min_months_per_year must be between 1 and 12.")

    if (evidence_thresholds is None) != (recoverability_thresholds is None):
        raise ValueError(
            "Both evidence_thresholds and recoverability_thresholds must be provided together, or both omitted."
        )

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
    values = sample[value_col]

    # Calculate amplitude_snr (corrected legacy diagnostic)
    if not sample.empty:
        by_month = values.groupby(values.index.month)
        climatology = by_month.mean()
        amplitude = float(climatology.max() - climatology.min())
        within_month_sd = (
            float(by_month.std().mean()) if len(qualifying_years) > 1 else 0.0
        )
    else:
        climatology = pd.Series(dtype=float)
        amplitude = 0.0
        within_month_sd = 0.0

    if within_month_sd > 0.0:
        snr = float(amplitude / within_month_sd)
    elif amplitude <= 0.0:
        snr = 0.0
    else:
        snr = float(
            amplitude / max(measurement_tolerance_pct, np.finfo(float).eps)
        )

    # Circular timing and drift
    peak_month_sets = annual_extremum_month_sets(
        sample, kind="max", tolerance_pct=0.0
    )
    trough_month_sets = annual_extremum_month_sets(
        sample, kind="min", tolerance_pct=0.0
    )
    peak_timing = summarise_annual_timing(
        peak_month_sets, n_resamples=n_bootstrap, random_state=random_state
    )
    trough_timing = summarise_annual_timing(
        trough_month_sets, n_resamples=n_bootstrap, random_state=random_state
    )

    min_drift_years = (
        evidence_thresholds.min_timing_years
        if evidence_thresholds is not None
        else 10
    )
    peak_drift = timing_drift(
        peak_month_sets,
        min_timing_years=min_drift_years,
        random_state=random_state,
    )
    trough_drift = timing_drift(
        trough_month_sets,
        min_timing_years=min_drift_years,
        random_state=random_state,
    )

    # Seasonality harmonic analysis
    if evidence_thresholds is not None:
        mode_freq = evidence_thresholds.mode_min_frequency
        mode_sep = evidence_thresholds.mode_min_separation_months
        boot_n = max(n_bootstrap, 1)
    else:
        mode_freq = None
        mode_sep = None
        boot_n = n_bootstrap

    pattern_res = classify_seasonal_pattern(
        prepared,
        measurement_tolerance_pct=measurement_tolerance_pct,
        mode_min_frequency=mode_freq,
        mode_min_separation_months=mode_sep,
        n_bootstrap=boot_n,
        n_null=max(n_bootstrap, 99),
        random_state=random_state,
        quality_policy=quality_policy,
    )

    # Events extraction
    event_summary = extract_water_events(
        extent,
        value_col=value_col,
        date_col=date_col,
        max_invalid_pct=max_invalid_pct,
        quality_policy=quality_policy,
    ).summary
    n_wet_events = event_summary["n_events"]
    longest_low = event_summary["longest_low_spell_months"]
    years_without = event_summary["years_without_event"]

    if len(qualifying_years) < _MIN_USABLE_YEARS:
        return WaterRegimeAssessment(
            regime="insufficient_record",
            amplitude_snr=0.0,
            peak_phase_iqr_months=None,
            peak_timing_concentration=None,
            peak_timing_concentration_ci_low=None,
            peak_timing_concentration_ci_high=None,
            peak_timing_uniformity_p=None,
            trough_phase_iqr_months=None,
            trough_timing_concentration=None,
            trough_timing_concentration_ci_low=None,
            trough_timing_concentration_ci_high=None,
            trough_timing_uniformity_p=None,
            n_timing_years=0,
            climatological_peak_month=None,
            climatological_trough_month=None,
            n_usable_years=len(qualifying_years),
            n_usable_months=int(len(usable)),
            n_wet_events=0,
            longest_low_spell_months=0,
            years_without_wet_event=0,
            recommended_action=_ACTIONS["insufficient_record"],
            caveats=tuple(caveats),
            seasonal_amplitude_pp=pattern_res.seasonal_amplitude_pp,
            amplitude_noise_ratio=pattern_res.amplitude_noise_ratio,
            seasonal_cv_skill=pattern_res.seasonal_cv_skill,
            periodicity_p=pattern_res.periodicity_p,
            selected_harmonic_order=pattern_res.selected_harmonic_order,
            peak_timing_n_modes=pattern_res.peak_timing_n_modes,
            trough_timing_n_modes=pattern_res.trough_timing_n_modes,
            peak_timing_drift_months_per_decade=peak_drift.months_per_decade,
            trough_timing_drift_months_per_decade=trough_drift.months_per_decade,
            peak_timing_drift_status=peak_drift.status,
            trough_timing_drift_status=trough_drift.status,
            annual_cycle_evidence="insufficient",
            boundary_cv_n=0,
            boundary_cv_coverage=0.0,
            boundary_cv_within_1_month=0.0,
            boundary_cv_within_1_month_wilson_low=0.0,
            boundary_cv_p90_error_months=12.0,
            boundary_recoverability="insufficient",
            boundary_recoverability_reason=f"{len(qualifying_years)} usable years below minimum {_MIN_USABLE_YEARS}",
        )

    if evidence_thresholds is not None and recoverability_thresholds is not None:
        at_or_below_floor = (
            pattern_res.seasonal_amplitude_pp <= measurement_tolerance_pct
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
        regime = _regime_from_evidence(
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
    else:
        # Non-release Plan 2 calibration bridge
        legacy_peak_timing = summarise_circular_months(
            [
                int(group[value_col].idxmax().month)
                for _, group in qualifying_groups
            ],
            n_resamples=n_bootstrap,
            random_state=random_state,
        )
        regime = _classify_legacy(snr, legacy_peak_timing)
        evidence = "insufficient"
        boundary_rec = BoundaryRecoverability(
            n=0,
            coverage=0.0,
            within_1_month=0.0,
            within_1_month_wilson_low=0.0,
            p90_error_months=12.0,
            state="insufficient",
            reason="calibration defaults not installed",
        )

    # Peak/trough assignment
    if regime in ("seasonal", "marginal"):
        peak_month = (
            pattern_res.expected_peak_month
            if pattern_res.expected_peak_month is not None
            else (int(climatology.idxmax()) if not climatology.empty else None)
        )
        trough_month = (
            pattern_res.expected_trough_month
            if pattern_res.expected_trough_month is not None
            else (int(climatology.idxmin()) if not climatology.empty else None)
        )
    else:
        peak_month = trough_month = None

    if _MIN_USABLE_YEARS <= peak_timing.n_years < _TIMING_RECORD_CAUTION_YEARS:
        caveats.append(
            "fewer than 30 usable annual timings: classification is retained, "
            "but uncertainty intervals may be wide"
        )
    if (
        _MIN_USABLE_YEARS <= peak_timing.n_years < _UNIFORMITY_MIN_TIMING_YEARS
        and snr >= _SEASONAL_MIN_SNR
        and peak_timing.ci_low is not None
        and peak_timing.ci_low < _STRONG_TIMING_CONCENTRATION
        and peak_timing.uniformity_p is not None
        and peak_timing.uniformity_p >= _CIRCULAR_UNIFORMITY_ALPHA
    ):
        caveats.append(
            "the circular-uniformity result has little power with fewer than "
            "10 annual timings, so the record remains marginal"
        )
    if regime == "marginal":
        caveats.append(
            "peak-timing concentration does not provide strong enough evidence "
            "for per-year boundaries, so the climatological peak describes "
            "average behaviour only"
        )
    if regime == "aseasonal":
        caveats.append(
            "no reproducible annual cycle: peak and trough are withheld because "
            "any value would reflect noise rather than a seasonal signal"
        )
    if years_without:
        caveats.append(
            f"{years_without} of {len(qualifying_groups)} usable years contain no "
            "wet event above the record's own 75th percentile"
        )

    return WaterRegimeAssessment(
        regime=regime,
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
        n_timing_years=peak_timing.n_years,
        climatological_peak_month=peak_month,
        climatological_trough_month=trough_month,
        n_usable_years=len(qualifying_years),
        n_usable_months=int(len(usable)),
        n_wet_events=n_wet_events,
        longest_low_spell_months=longest_low,
        years_without_wet_event=years_without,
        recommended_action=_ACTIONS[regime],
        caveats=tuple(caveats),
        seasonal_amplitude_pp=pattern_res.seasonal_amplitude_pp,
        amplitude_noise_ratio=pattern_res.amplitude_noise_ratio,
        seasonal_cv_skill=pattern_res.seasonal_cv_skill,
        periodicity_p=pattern_res.periodicity_p,
        selected_harmonic_order=pattern_res.selected_harmonic_order,
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


PublicRoute = Literal[
    "per_year_detection", "event_characterisation", "insufficient_record"
]


def public_route(regime: Regime, recoverability: str) -> PublicRoute:
    """Map regime and boundary recoverability to the public route.

    Regime alone never authorises publication. A seasonal record whose troughs
    do not reproduce out of sample routes to events, and a marginal record
    whose troughs do reproduce is allowed dynamic years.
    """
    if regime == "insufficient_record":
        return "insufficient_record"
    if regime in {"seasonal", "marginal"} and recoverability == "supported":
        return "per_year_detection"
    return "event_characterisation"


__all__ = [
    "PublicRoute",
    "REGIME_THRESHOLDS",
    "Regime",
    "WaterRegimeAssessment",
    "assess_water_regime",
    "public_route",
]
