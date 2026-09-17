from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Regime = Literal["seasonal", "aseasonal", "insufficient_record"]
Route = Literal[
    "per_year_detection",
    "event_characterisation",
    "insufficient_record",
]
DecisionPolicy = Literal["hydroseason_0_2_0"]
DECISION_POLICY: DecisionPolicy = "hydroseason_0_2_0"
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
    implementation_policy: DecisionPolicy = "hydroseason_0_2_0"


def decide_regime(
    *,
    classification: str | None,
    status: str,
    reason: str,
) -> EstablishedDecision:
    """Map a timing-recurrence result onto regime and route.

    The method has two classes. ``aseasonal`` states that recurrence was
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
        policy="hydroseason_0_2_0",
        regime=regime,
        route=route,
        supports_per_year_boundaries=route == "per_year_detection",
        supports_fixed_window=False,
        timing_evidence=timing_evidence,
        reason=(
            f"policy=hydroseason_0_2_0: regime={regime}; "
            f"status={status}; reason={reason}; route={route}"
        ),
        implementation_policy="hydroseason_0_2_0",
    )

