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

from ._circular_timing import (
    AnnualTimingSummary,
    summarise_annual_timing,
)
from ._decision_policy import (
    DECISION_POLICY,
    REGIME_THRESHOLDS,
    DecisionPolicy,
    EstablishedDecision,
    Regime,
    Route,
    TimingEvidence,
    decide_regime,
)
from ._events import extract_water_events
from ._scientific_defaults import TIMING_IDENTIFIABILITY_DEFAULTS
from ._seasonality_test import TimingRecurrenceResult, assess_timing_recurrence
from ._state_input import QualityPolicy, prepare_monthly_extent
from ._timing_identifiability import (
    PixelSupportStatus,
    RecordTimingEvidence,
    assess_timing_identifiability,
)

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
    timing_evidence: TimingEvidence
    n_peak_timing_years: int
    n_trough_timing_years: int
    n_zero_months: int
    zero_month_fraction: float
    n_whole_zero_years: int
    pixel_support_status: PixelSupportStatus
    mean_monthly_peak_month: int | None
    mean_monthly_trough_month: int | None
    n_usable_years: int
    n_usable_months: int
    n_wet_events: int
    longest_low_spell_months: int
    years_without_wet_event: int
    recommended_action: str
    caveats: tuple[str, ...]

    seasonality_test: TimingRecurrenceResult | None = None
    decision_policy: DecisionPolicy = DECISION_POLICY
    public_route: Route = "insufficient_record"

    @property
    def supports_per_year_boundaries(self) -> bool:
        """Whether public hydrological years may be published for this record."""
        return self.public_route == "per_year_detection"

    @property
    def attempts_per_year_detection(self) -> bool:
        """Whether the detector runs at all, as an internal diagnostic."""
        return self.regime == "seasonal"

    @property
    def supports_fixed_window(self) -> bool:
        """Whether one fixed climatological wet/dry window is defensible."""
        return False



_ACTIONS: dict[Regime, str] = {
    "seasonal": (
        "Run per-year hydrological-year detection. Peak and trough months are "
        "reproducible year to year."
    ),
    "aseasonal": (
        "Do not define a hydrological year: annual timing was not established "
        "by the current evidence. This label covers both a record that "
        "genuinely lacks a reproducible annual cycle and one where insufficient "
        "concentration, power, or informative years left annual timing "
        "unresolved -- a non-significant test does not prove uniform timing. "
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
    measurement_tolerance_pct: float = 0.0,
    n_bootstrap: int = 200,
    random_state: int = 0,
) -> WaterRegimeAssessment:
    """Assess what the observed surface-water record supports."""
    if not 1 <= min_months_per_year <= 12:
        raise ValueError("min_months_per_year must be between 1 and 12.")

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

    if sample.empty:
        count_columns = {"n_water", "n_valid", "n_invalid", "n_aoi"}
        timing_evidence = RecordTimingEvidence(
            years={},
            pixel_support_status=(
                "available" if count_columns.issubset(prepared.columns) else "unavailable"
            ),
            n_zero_months=0,
            zero_month_fraction=0.0,
            n_whole_zero_years=0,
            n_peak_timing_years=0,
            n_trough_timing_years=0,
            n_timing_years=0,
        )
    else:
        timing_evidence = assess_timing_identifiability(
            sample,
            thresholds=TIMING_IDENTIFIABILITY_DEFAULTS,
            value_col=value_col,
            max_invalid_pct=max_invalid_pct,
            quality_policy=quality_policy,
            measurement_tolerance_pct=measurement_tolerance_pct,
        )

    peak_month_sets = {
        year: annual.peak_months
        for year, annual in timing_evidence.years.items()
        if annual.peak_status != "unresolved"
    }
    trough_month_sets = {
        year: annual.trough_months
        for year, annual in timing_evidence.years.items()
        if annual.trough_status != "unresolved"
    }
    peak_timing: AnnualTimingSummary = summarise_annual_timing(
        peak_month_sets,
        n_resamples=n_bootstrap,
        random_state=random_state,
    )
    trough_timing: AnnualTimingSummary = summarise_annual_timing(
        trough_month_sets,
        n_resamples=n_bootstrap,
        random_state=random_state,
    )

    if len(qualifying_years) < _MIN_USABLE_YEARS:
        snr = 0.0
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
    recurrence: TimingRecurrenceResult = assess_timing_recurrence(
        prepared,
        thresholds=TIMING_IDENTIFIABILITY_DEFAULTS,
        value_col=value_col,
        measurement_tolerance_pct=measurement_tolerance_pct,
        min_months_per_year=min_months_per_year,
        min_years=_MIN_USABLE_YEARS,
        n_bootstrap=n_bootstrap,
        random_state=random_state,
    )
    decision = decide_regime(
        classification=recurrence.classification,
        status=recurrence.status,
        reason=recurrence.reason,
    )

    populate_months = (
        decision.regime == "seasonal" and len(qualifying_years) >= _MIN_USABLE_YEARS
    )
    mean_monthly_peak_month = int(climatology.idxmax()) if populate_months else None
    mean_monthly_trough_month = int(climatology.idxmin()) if populate_months else None

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

    caveats.append(
        "seasonality policy hydroseason-v0.2.0: class decided by calendar recurrence of annual peak and trough timing at "
        f"alpha {recurrence.alpha:g}; aseasonal means recurrence was not established, "
        "not that timing is uniform"
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
        n_timing_years=timing_evidence.n_peak_timing_years,
        timing_evidence=decision.timing_evidence,
        n_peak_timing_years=timing_evidence.n_peak_timing_years,
        n_trough_timing_years=timing_evidence.n_trough_timing_years,
        n_zero_months=timing_evidence.n_zero_months,
        zero_month_fraction=timing_evidence.zero_month_fraction,
        n_whole_zero_years=timing_evidence.n_whole_zero_years,
        pixel_support_status=timing_evidence.pixel_support_status,
        mean_monthly_peak_month=mean_monthly_peak_month,
        mean_monthly_trough_month=mean_monthly_trough_month,
        n_usable_years=len(qualifying_years),
        n_usable_months=int(len(usable)),
        n_wet_events=n_wet_events,
        longest_low_spell_months=longest_low,
        years_without_wet_event=years_without,
        recommended_action=_ACTIONS[decision.regime],
        caveats=tuple(caveats),
        seasonality_test=recurrence,
        decision_policy=decision.policy,
        public_route=decision.route,
    )


PublicRoute = Literal[
    "per_year_detection", "event_characterisation", "insufficient_record"
]


def public_route(regime: Regime) -> PublicRoute:
    """Map regime to public route."""
    if regime == "seasonal":
        return "per_year_detection"
    if regime == "insufficient_record":
        return "insufficient_record"
    return "event_characterisation"


__all__ = [
    "DecisionPolicy",
    "DECISION_POLICY",
    "EstablishedDecision",
    "PublicRoute",
    "REGIME_THRESHOLDS",
    "Regime",
    "Route",
    "WaterRegimeAssessment",
    "assess_water_regime",
    "decide_regime",
    "public_route",
]
