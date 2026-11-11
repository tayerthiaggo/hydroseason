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


@dataclass(frozen=True)
class EstablishedDecision:
    policy: DecisionPolicy
    regime: Regime
    route: Route
    timing_evidence: TimingEvidence


def decide_regime(
    *,
    classification: str | None,
    status: str,
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
        timing_evidence=timing_evidence,
    )

