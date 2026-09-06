from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from ._timing_identifiability import TimingStatus

RefinementStatus = Literal[
    "confirmed",
    "provisional",
    "unresolved",
    "unavailable",
    "awaiting_next_peak",
]
PeakQuality = Literal["normal", "low", "unknown", "missing"]


@dataclass(frozen=True)
class TroughRefinementPolicy:
    huber_k: float
    profile_loss_cutoff: float
    pulse_z: float
    version: str = "trough_refinement_candidate_0_1"

    def __post_init__(self) -> None:
        if self.huber_k <= 0.0:
            raise ValueError("huber_k must be positive.")
        if self.profile_loss_cutoff < 0.0:
            raise ValueError("profile_loss_cutoff must be non-negative.")
        if self.pulse_z <= 0.0:
            raise ValueError("pulse_z must be positive.")
        if not self.version:
            raise ValueError("version must not be empty.")


@dataclass(frozen=True)
class PeakBoundary:
    selected: pd.Timestamp | None
    candidates: tuple[pd.Timestamp, ...]
    timing_status: TimingStatus
    quality: PeakQuality

    @classmethod
    def missing(cls) -> PeakBoundary:
        return cls(
            selected=None,
            candidates=(),
            timing_status="unresolved",
            quality="missing",
        )


@dataclass(frozen=True)
class TroughRefinementResult:
    status: RefinementStatus
    reason: str
    boundary: pd.Timestamp | None
    boundary_candidates: tuple[pd.Timestamp, ...]
    low_state_start: pd.Timestamp | None
    low_state_end: pd.Timestamp | None
    recovery_start: pd.Timestamp | None
    pulse_months: tuple[pd.Timestamp, ...]
    local_scale_pp: float
    best_loss: float
    effective_support: float
    policy_version: str


def _empty_result(
    status: RefinementStatus,
    reason: str,
    policy: TroughRefinementPolicy,
) -> TroughRefinementResult:
    return TroughRefinementResult(
        status=status,
        reason=reason,
        boundary=None,
        boundary_candidates=(),
        low_state_start=None,
        low_state_end=None,
        recovery_start=None,
        pulse_months=(),
        local_scale_pp=0.0,
        best_loss=float("nan"),
        effective_support=0.0,
        policy_version=policy.version,
    )


def refine_trough_span(
    frame: pd.DataFrame,
    *,
    left_peak: PeakBoundary,
    right_peak: PeakBoundary | None,
    policy: TroughRefinementPolicy,
) -> TroughRefinementResult:
    """Challenge one pass-1 trough inside an ordered peak-to-peak span."""
    if right_peak is None:
        return _empty_result("awaiting_next_peak", "open_span", policy)
    if (
        left_peak.selected is None
        or right_peak.selected is None
        or left_peak.timing_status == "unresolved"
        or right_peak.timing_status == "unresolved"
    ):
        return _empty_result(
            "unavailable",
            "missing_or_unresolved_peak",
            policy,
        )
    raise NotImplementedError("eligible trough refinement is not implemented")
