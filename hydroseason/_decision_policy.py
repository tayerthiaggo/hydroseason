from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ._circular_timing import CircularTimingSummary

Regime = Literal["seasonal", "marginal", "aseasonal", "insufficient_record"]
Route = Literal[
    "per_year_detection",
    "fixed_climatological_window",
    "event_characterisation",
    "insufficient_record",
]
DecisionPolicy = Literal["established_0_1_1"]
ESTABLISHED_POLICY: DecisionPolicy = "established_0_1_1"

REGIME_THRESHOLDS = {
    "seasonal_min_snr": 2.0,
    "strong_timing_concentration": 0.70,
    "weak_timing_concentration": 0.30,
    "aseasonal_max_snr": 0.70,
    "circular_uniformity_alpha": 0.10,
    "uniformity_min_timing_years": 10.0,
    "timing_record_caution_years": 30.0,
}


@dataclass(frozen=True)
class EstablishedDecision:
    policy: DecisionPolicy
    regime: Regime
    route: Route
    supports_per_year_boundaries: bool
    supports_fixed_window: bool
    reason: str


def decide_established(
    *,
    n_usable_years: int,
    amplitude_snr: float,
    peak_timing: CircularTimingSummary,
    trough_timing: CircularTimingSummary,
) -> EstablishedDecision:
    t = REGIME_THRESHOLDS
    if n_usable_years < 5:
        regime: Regime = "insufficient_record"
    elif amplitude_snr >= t["seasonal_min_snr"] and peak_timing.ci_low is not None and peak_timing.ci_low >= t["strong_timing_concentration"]:
        regime = "seasonal"
    elif amplitude_snr < t["aseasonal_max_snr"]:
        regime = "aseasonal"
    elif peak_timing.uniformity_p is not None and peak_timing.uniformity_p >= t["circular_uniformity_alpha"] and peak_timing.n >= t["uniformity_min_timing_years"]:
        regime = "aseasonal"
    else:
        regime = "marginal"

    per_year = regime == "seasonal" and trough_timing.ci_low is not None and trough_timing.ci_low >= t["strong_timing_concentration"]
    timing = (
        peak_timing.uniformity_p,
        trough_timing.uniformity_p,
        peak_timing.concentration,
        trough_timing.concentration,
    )
    fixed = regime == "seasonal" or (
        regime == "marginal"
        and all(value is not None for value in timing)
        and peak_timing.uniformity_p < t["circular_uniformity_alpha"]
        and trough_timing.uniformity_p < t["circular_uniformity_alpha"]
        and peak_timing.concentration >= t["weak_timing_concentration"]
        and trough_timing.concentration >= t["weak_timing_concentration"]
    )
    if regime == "insufficient_record":
        route: Route = "insufficient_record"
    elif per_year:
        route = "per_year_detection"
    elif fixed:
        route = "fixed_climatological_window"
    else:
        route = "event_characterisation"
    reason = f"{ESTABLISHED_POLICY}: regime={regime}; route={route}; amplitude_snr={amplitude_snr:.3f}"
    return EstablishedDecision(ESTABLISHED_POLICY, regime, route, per_year, fixed, reason)
