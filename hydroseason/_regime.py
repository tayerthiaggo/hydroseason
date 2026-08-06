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

Two scale-free diagnostics drive the classification:

``amplitude_snr``
    Climatological amplitude (wettest mean month minus driest) divided by the
    mean within-month interannual standard deviation. Reads as: is the average
    year's cycle larger than the difference between years? Being a ratio it is
    invariant to absolute extent, so catchments whose entire signal sits under
    1% are judged on the same footing as far wetter ones.

``peak_phase_iqr_months``
    Circular interquartile range of the per-year peak month. Reads as: do
    individual years agree on *when* the wet phase happens? A pooled
    climatology can look tidy while every constituent year peaks somewhere
    different; this catches that, and a leave-one-out jackknife does not
    (dropping one year of forty barely perturbs a pooled mean, so such
    measures report near-perfect stability for every catchment and
    discriminate nothing).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from ._events import extract_water_events
from ._state_input import QualityPolicy, prepare_monthly_extent

Regime = Literal["seasonal", "marginal", "aseasonal", "insufficient_record"]

# A year is usable with most months present, not all twelve. The all-or-nothing
# rule this replaces is not neutral: wet-season cloud removes precisely the
# months carrying the monsoon peak, so completeness anti-correlates with
# seasonality and the strictest interpretation discards the most seasonal
# catchments first.
_DEFAULT_MIN_MONTHS_PER_YEAR = 9
_MIN_USABLE_YEARS = 5

# Boundaries between regimes. Deliberately wide apart, with everything between
# them landing in "marginal" rather than being forced to a side.
_SEASONAL_MIN_SNR = 2.0
_SEASONAL_MAX_PHASE_IQR = 1.5
_ASEASONAL_MAX_SNR = 0.7
_ASEASONAL_MIN_PHASE_IQR = 3.5

# Published so the report can state the cut-offs it is judging against. A
# reader shown "SNR 2.46" and nothing else cannot tell a strong number from a
# weak one, and a second copy of these values in the report layer would
# eventually disagree with the classifier that actually decides the regime.
REGIME_THRESHOLDS: dict[str, float] = {
    "seasonal_min_snr": _SEASONAL_MIN_SNR,
    "seasonal_max_phase_iqr_months": _SEASONAL_MAX_PHASE_IQR,
    "aseasonal_max_snr": _ASEASONAL_MAX_SNR,
    "aseasonal_min_phase_iqr_months": _ASEASONAL_MIN_PHASE_IQR,
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
    climatological_peak_month: int | None
    climatological_trough_month: int | None
    n_usable_years: int
    n_usable_months: int
    n_wet_events: int
    longest_low_spell_months: int
    years_without_wet_event: int
    recommended_action: str
    caveats: tuple[str, ...]

    @property
    def supports_per_year_boundaries(self) -> bool:
        """Whether a peak/trough may be reported for each individual year."""
        return self.regime == "seasonal"

    @property
    def supports_fixed_window(self) -> bool:
        """Whether one fixed climatological wet/dry window is defensible.

        True for marginal records as an explicit average-behaviour frame: the
        pooled climatology carries a reproducible phase even where single years
        do not. It is an analytical choice the caller imposes, not a finding.
        """
        return self.regime in ("seasonal", "marginal")


def _circular_iqr_months(months: list[int]) -> float | None:
    """Interquartile spread of calendar months on the circle, in months.

    Plain percentiles would treat December and January as eleven months apart;
    resolving the spread about the circular mean keeps a Dec/Jan pair adjacent.
    """
    if len(months) < 4:
        return None
    radians = 2.0 * np.pi * (np.asarray(months) - 1) / 12.0
    centre = np.angle(np.mean(np.exp(1j * radians)))
    offsets = np.angle(np.exp(1j * (radians - centre))) * 12.0 / (2.0 * np.pi)
    return float(np.percentile(offsets, 75) - np.percentile(offsets, 25))


def _classify(snr: float, phase_iqr: float | None) -> Regime:
    if phase_iqr is None:
        return "marginal" if snr >= _SEASONAL_MIN_SNR else "aseasonal"
    if snr >= _SEASONAL_MIN_SNR and phase_iqr <= _SEASONAL_MAX_PHASE_IQR:
        return "seasonal"
    if snr < _ASEASONAL_MAX_SNR or phase_iqr >= _ASEASONAL_MIN_PHASE_IQR:
        return "aseasonal"
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
    quality_policy: QualityPolicy = "exclude",
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

    prepared = prepare_monthly_extent(
        extent,
        value_col=value_col,
        date_col=date_col,
        max_invalid_pct=max_invalid_pct,
        quality_policy=quality_policy,
    )
    usable = prepared.loc[prepared["candidate_usable"]]
    caveats = [_SCOPE_CAVEAT, _DRIVER_CAVEAT]

    qualifying_years = [
        year
        for year, group in usable.groupby(usable.index.year)
        if len(set(group.index.month)) >= min_months_per_year
    ]
    sample = usable.loc[usable.index.year.isin(qualifying_years)]
    values = sample[value_col]

    if len(qualifying_years) < _MIN_USABLE_YEARS:
        return WaterRegimeAssessment(
            regime="insufficient_record",
            amplitude_snr=0.0,
            peak_phase_iqr_months=None,
            climatological_peak_month=None,
            climatological_trough_month=None,
            n_usable_years=len(qualifying_years),
            n_usable_months=int(len(usable)),
            n_wet_events=0,
            longest_low_spell_months=0,
            years_without_wet_event=0,
            recommended_action=_ACTIONS["insufficient_record"],
            caveats=tuple(caveats),
        )

    by_month = values.groupby(values.index.month)
    climatology = by_month.mean()
    amplitude = float(climatology.max() - climatology.min())
    within_month_sd = float(by_month.std().mean())
    # Ratio, not a difference against a fixed pp floor: an absolute tolerance
    # silently rejects any catchment whose entire signal is small.
    snr = amplitude / within_month_sd if within_month_sd > 0 else np.inf

    per_year_peaks = [
        int(group[value_col].idxmax().month)
        for _, group in sample.groupby(sample.index.year)
        if len(group) >= min_months_per_year and group[value_col].notna().any()
    ]
    phase_iqr = _circular_iqr_months(per_year_peaks)

    regime = _classify(snr, phase_iqr)
    # One definition of an event, shared with the event module. A private
    # second implementation here drifted from it -- different thresholds, no
    # hysteresis -- so the same record reported different counts depending on
    # which entry point the caller used.
    event_summary = extract_water_events(
        extent, value_col=value_col, date_col=date_col,
        max_invalid_pct=max_invalid_pct, quality_policy=quality_policy,
    ).summary
    n_wet_events = event_summary["n_events"]
    longest_low = event_summary["longest_low_spell_months"]
    years_without = event_summary["years_without_event"]

    # Withhold a headline peak/trough where the record cannot support one,
    # rather than emitting a number the caller has to know to distrust.
    if regime in ("seasonal", "marginal"):
        peak_month: int | None = int(climatology.idxmax())
        trough_month: int | None = int(climatology.idxmin())
    else:
        peak_month = trough_month = None

    if regime == "marginal":
        caveats.append(
            f"per-year peak timing varies by ~{phase_iqr:.1f} months, so the "
            "climatological peak describes average behaviour only"
        )
    if regime == "aseasonal":
        caveats.append(
            "no reproducible annual cycle: peak and trough are withheld because "
            "any value would reflect noise rather than a seasonal signal"
        )
    if years_without:
        caveats.append(
            f"{years_without} of {len(qualifying_years)} usable years contain no "
            "wet event above the record's own 75th percentile"
        )

    return WaterRegimeAssessment(
        regime=regime,
        amplitude_snr=float(snr),
        peak_phase_iqr_months=phase_iqr,
        climatological_peak_month=peak_month,
        climatological_trough_month=trough_month,
        n_usable_years=len(qualifying_years),
        n_usable_months=int(len(usable)),
        n_wet_events=n_wet_events,
        longest_low_spell_months=longest_low,
        years_without_wet_event=years_without,
        recommended_action=_ACTIONS[regime],
        caveats=tuple(caveats),
    )


__all__ = [
    "REGIME_THRESHOLDS",
    "Regime",
    "WaterRegimeAssessment",
    "assess_water_regime",
]
