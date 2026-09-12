from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ._circular_timing import AnnualTimingSummary

Regime = Literal["seasonal", "marginal", "aseasonal", "insufficient_record"]
Route = Literal[
    "per_year_detection",
    "fixed_climatological_window",
    "event_characterisation",
    "insufficient_record",
]
DecisionPolicy = Literal[
    "established_0_1_1", "established_0_2_0", "candidate_timing_recurrence"
]
SeasonalityPolicy = Literal["timing_recurrence"]
ESTABLISHED_POLICY: DecisionPolicy = "established_0_2_0"
CANDIDATE_POLICY: DecisionPolicy = "established_0_2_0"
CANDIDATE_TIMING_RECURRENCE_POLICY: DecisionPolicy = "candidate_timing_recurrence"
TimingEvidence = Literal["supported", "insufficient", "unsupported"]

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
    timing_evidence: TimingEvidence
    reason: str
    implementation_policy: DecisionPolicy = CANDIDATE_POLICY


def decide_established(
    *,
    n_usable_years: int,
    amplitude_snr: float,
    peak_timing: AnnualTimingSummary,
    trough_timing: AnnualTimingSummary,
    n_peak_timing_years: int,
    n_trough_timing_years: int,
    min_informative_years: int,
) -> EstablishedDecision:
    t = REGIME_THRESHOLDS
    if n_usable_years < 5:
        regime: Regime = "insufficient_record"
    elif amplitude_snr >= t["seasonal_min_snr"] and peak_timing.ci_low is not None and peak_timing.ci_low >= t["strong_timing_concentration"]:
        regime = "seasonal"
    elif amplitude_snr < t["aseasonal_max_snr"]:
        regime = "aseasonal"
    elif peak_timing.uniformity_p is not None and peak_timing.uniformity_p >= t["circular_uniformity_alpha"] and peak_timing.n_years >= t["uniformity_min_timing_years"]:
        regime = "aseasonal"
    else:
        regime = "marginal"

    if min(n_peak_timing_years, n_trough_timing_years) < min_informative_years:
        timing_evidence: TimingEvidence = "insufficient"
    elif regime == "aseasonal":
        timing_evidence = "unsupported"
    else:
        timing_evidence = "supported"

    per_year = regime in {"seasonal", "marginal"} and timing_evidence == "supported"
    fixed = False
    if regime == "insufficient_record":
        route: Route = "insufficient_record"
    elif per_year:
        route = "per_year_detection"
    else:
        route = "event_characterisation"
    reason = (
        f"candidate={CANDIDATE_POLICY}; authority={ESTABLISHED_POLICY}: "
        f"regime={regime}; timing_evidence={timing_evidence}; route={route}; "
        f"amplitude_snr={amplitude_snr:.3f}"
    )
    return EstablishedDecision(
        policy=ESTABLISHED_POLICY,
        regime=regime,
        route=route,
        supports_per_year_boundaries=per_year,
        supports_fixed_window=fixed,
        timing_evidence=timing_evidence,
        reason=reason,
    )


def decide_timing_recurrence(
    *,
    classification: str | None,
    status: str,
    reason: str,
) -> EstablishedDecision:
    """Map a timing-recurrence result onto regime and route.

    The candidate has two classes. ``aseasonal`` states that recurrence was
    not established; it is not a claim that timing is uniform, and an
    insufficient record is never folded into it.
    """
    if status != "ok":
        regime: Regime = "insufficient_record"
        route: Route = "insufficient_record"
        timing_evidence: TimingEvidence = "insufficient"
    elif classification == "seasonal":
        regime, route, timing_evidence = "seasonal", "per_year_detection", "supported"
    else:
        regime, route, timing_evidence = (
            "aseasonal",
            "event_characterisation",
            "unsupported",
        )
    return EstablishedDecision(
        policy=CANDIDATE_TIMING_RECURRENCE_POLICY,
        regime=regime,
        route=route,
        supports_per_year_boundaries=route == "per_year_detection",
        supports_fixed_window=False,
        timing_evidence=timing_evidence,
        reason=(
            f"candidate={CANDIDATE_TIMING_RECURRENCE_POLICY}: regime={regime}; "
            f"status={status}; reason={reason}; route={route}"
        ),
        implementation_policy=CANDIDATE_TIMING_RECURRENCE_POLICY,
    )
