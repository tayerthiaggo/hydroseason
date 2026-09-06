from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from ._scientific_defaults import TIMING_IDENTIFIABILITY_DEFAULTS
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


@dataclass(frozen=True)
class _CandidateFit:
    start_position: int
    end_position: int
    fitted: np.ndarray
    loss: float
    converged: bool


_MAX_IRLS_ITERATIONS = 200
_RELATIVE_CONVERGENCE = float(np.sqrt(np.finfo(float).eps))


def _weighted_pava(
    values: np.ndarray,
    weights: np.ndarray,
    *,
    increasing: bool,
) -> np.ndarray:
    """Weighted least-squares isotonic fit using pooled adjacent violators."""
    if values.size == 0:
        return values.copy()
    work = values if increasing else -values
    blocks: list[list[float | int]] = []
    for position, (value, weight) in enumerate(zip(work, weights, strict=True)):
        blocks.append([position, position + 1, float(weight), float(weight * value)])
        while len(blocks) >= 2:
            previous = blocks[-2]
            current = blocks[-1]
            previous_mean = float(previous[3]) / float(previous[2])
            current_mean = float(current[3]) / float(current[2])
            if previous_mean <= current_mean:
                break
            blocks[-2:] = [[
                int(previous[0]),
                int(current[1]),
                float(previous[2]) + float(current[2]),
                float(previous[3]) + float(current[3]),
            ]]
    fitted = np.empty(values.size, dtype=float)
    for start, stop, weight, weighted_sum in blocks:
        fitted[int(start):int(stop)] = float(weighted_sum) / float(weight)
    return fitted if increasing else -fitted


def _valley_for_level(
    values: np.ndarray,
    weights: np.ndarray,
    start: int,
    end: int,
    level: float,
) -> np.ndarray:
    fitted = np.full(values.size, level, dtype=float)
    if start:
        outward = _weighted_pava(
            values[:start][::-1],
            weights[:start][::-1],
            increasing=True,
        )
        fitted[:start] = np.maximum(outward, level)[::-1]
    if end + 1 < values.size:
        outward = _weighted_pava(
            values[end + 1:],
            weights[end + 1:],
            increasing=True,
        )
        fitted[end + 1:] = np.maximum(outward, level)
    return fitted


def _fit_valley_l2(
    values: np.ndarray,
    weights: np.ndarray,
    start: int,
    end: int,
) -> np.ndarray:
    """Fit one fixed low-state block under squared loss."""
    lower = float(np.min(values))
    upper = float(np.max(values))
    if lower == upper:
        return np.full(values.size, lower, dtype=float)

    ratio = (np.sqrt(5.0) - 1.0) / 2.0

    def objective(level: float) -> tuple[float, np.ndarray]:
        fitted = _valley_for_level(values, weights, start, end, level)
        return float(np.sum(weights * np.square(values - fitted))), fitted

    left = lower
    right = upper
    x1 = right - ratio * (right - left)
    x2 = left + ratio * (right - left)
    f1, _ = objective(x1)
    f2, _ = objective(x2)
    for _ in range(96):
        if f1 <= f2:
            right = x2
            x2 = x1
            f2 = f1
            x1 = right - ratio * (right - left)
            f1, _ = objective(x1)
        else:
            left = x1
            x1 = x2
            f1 = f2
            x2 = left + ratio * (right - left)
            f2, _ = objective(x2)
    _, fitted = objective((left + right) / 2.0)
    return fitted


def _fit_valley_l1(
    values: np.ndarray,
    weights: np.ndarray,
    start: int,
    end: int,
) -> _CandidateFit:
    fitted = _fit_valley_l2(values, weights, start, end)
    epsilon = max(
        np.finfo(float).eps,
        float(np.ptp(values)) * _RELATIVE_CONVERGENCE,
    )
    converged = False
    for _ in range(_MAX_IRLS_ITERATIONS):
        residual = values - fitted
        effective = weights / np.maximum(np.abs(residual), epsilon)
        updated = _fit_valley_l2(values, effective, start, end)
        tolerance = max(
            np.finfo(float).eps,
            _RELATIVE_CONVERGENCE
            * max(1.0, float(np.max(np.abs(values)))),
        )
        if float(np.max(np.abs(updated - fitted))) <= tolerance:
            fitted = updated
            converged = True
            break
        fitted = updated
    return _CandidateFit(
        start_position=start,
        end_position=end,
        fitted=fitted,
        loss=float(np.sum(weights * np.abs(values - fitted))),
        converged=converged,
    )


def _fit_valley_huber(
    values: np.ndarray,
    weights: np.ndarray,
    start: int,
    end: int,
    *,
    scale: float,
    huber_k: float,
) -> _CandidateFit:
    fitted = _fit_valley_l2(values, weights, start, end)
    if scale == 0.0:
        residual = values - fitted
        return _CandidateFit(
            start_position=start,
            end_position=end,
            fitted=fitted,
            loss=float(np.sum(weights * np.abs(residual))),
            converged=True,
        )

    converged = False
    cutoff = huber_k * scale
    for _ in range(_MAX_IRLS_ITERATIONS):
        residual = values - fitted
        magnitude = np.abs(residual)
        robust = np.ones(values.size, dtype=float)
        outside = magnitude > cutoff
        robust[outside] = cutoff / magnitude[outside]
        updated = _fit_valley_l2(values, weights * robust, start, end)
        tolerance = max(
            np.finfo(float).eps,
            _RELATIVE_CONVERGENCE
            * max(scale, float(np.max(np.abs(values))), 1.0),
        )
        if float(np.max(np.abs(updated - fitted))) <= tolerance:
            fitted = updated
            converged = True
            break
        fitted = updated

    standardized = (values - fitted) / scale
    magnitude = np.abs(standardized)
    loss = np.where(
        magnitude <= huber_k,
        0.5 * np.square(standardized),
        huber_k * magnitude - 0.5 * huber_k**2,
    )
    return _CandidateFit(
        start_position=start,
        end_position=end,
        fitted=fitted,
        loss=float(np.sum(weights * loss)),
        converged=converged,
    )


def _median_absolute_deviation(values: np.ndarray) -> float:
    if values.size == 0:
        return 0.0
    median = float(np.median(values))
    return float(np.median(np.abs(values - median)))


def _measurement_floor(frame: pd.DataFrame) -> float:
    if "n_valid" not in frame.columns:
        return 0.0
    valid = pd.to_numeric(frame["n_valid"], errors="coerce")
    resolution = 100.0 / valid.loc[valid > 0.0]
    return float(resolution.median()) if len(resolution) else 0.0


def _local_scale(
    values: np.ndarray,
    preliminary: _CandidateFit,
    frame: pd.DataFrame,
) -> float:
    residual_scale = 1.4826 * _median_absolute_deviation(
        values - preliminary.fitted
    )
    if residual_scale > 0.0:
        return residual_scale
    difference_scale = (
        1.4826
        * _median_absolute_deviation(np.diff(values))
        / np.sqrt(2.0)
    )
    if difference_scale > 0.0:
        return float(difference_scale)
    return _measurement_floor(frame)


def _support_weights(frame: pd.DataFrame) -> np.ndarray:
    if "observed_fraction" in frame.columns:
        observed = pd.to_numeric(frame["observed_fraction"], errors="coerce")
        weights = observed.fillna(1.0).clip(lower=0.0, upper=1.0)
    else:
        weights = pd.Series(1.0, index=frame.index)
    return weights.to_numpy(dtype=float)


def _month_span(start: pd.Timestamp, end: pd.Timestamp) -> int:
    return (end.year - start.year) * 12 + end.month - start.month


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

    left_date = pd.Timestamp(left_peak.selected)
    right_date = pd.Timestamp(right_peak.selected)
    if left_date >= right_date or left_date not in frame.index or right_date not in frame.index:
        return _empty_result(
            "unavailable",
            "missing_or_unresolved_peak",
            policy,
        )

    span = frame.loc[left_date:right_date].copy()
    values_series = pd.to_numeric(span["extent_pct"], errors="coerce")
    weights = _support_weights(span)
    observed = values_series.notna().to_numpy() & (weights > 0.0)
    if len(span) < 3 or not bool(observed[0]) or not bool(observed[-1]):
        return _empty_result("unresolved", "no_defensible_low_state", policy)
    if not bool(observed.all()):
        return _empty_result("unresolved", "gap_overlaps_low_state", policy)

    values = values_series.to_numpy(dtype=float)
    preliminary = [
        _fit_valley_l1(values, weights, start, end)
        for start in range(1, len(span) - 1)
        for end in range(start, len(span) - 1)
    ]
    preliminary = [candidate for candidate in preliminary if candidate.converged]
    if not preliminary:
        return _empty_result("unresolved", "no_converged_candidate", policy)
    preliminary_best = min(
        preliminary,
        key=lambda candidate: (
            candidate.loss,
            candidate.end_position,
            candidate.start_position,
        ),
    )
    scale = _local_scale(values, preliminary_best, span)
    candidates = [
        _fit_valley_huber(
            values,
            weights,
            start,
            end,
            scale=scale,
            huber_k=policy.huber_k,
        )
        for start in range(1, len(span) - 1)
        for end in range(start, len(span) - 1)
    ]
    candidates = [candidate for candidate in candidates if candidate.converged]
    if not candidates:
        return _empty_result("unresolved", "no_converged_candidate", policy)

    endpoint_fits: dict[int, _CandidateFit] = {}
    for candidate in candidates:
        current = endpoint_fits.get(candidate.end_position)
        if current is None or candidate.loss < current.loss:
            endpoint_fits[candidate.end_position] = candidate
            continue
        tolerance = max(
            np.finfo(float).eps,
            _RELATIVE_CONVERGENCE * max(1.0, abs(current.loss)),
        )
        if (
            abs(candidate.loss - current.loss) <= tolerance
            and candidate.start_position < current.start_position
        ):
            endpoint_fits[candidate.end_position] = candidate

    best_loss = min(candidate.loss for candidate in endpoint_fits.values())
    effective_support = float(np.sum(weights))
    loss_tolerance = max(
        np.finfo(float).eps,
        _RELATIVE_CONVERGENCE * max(1.0, abs(best_loss)),
    )
    plausible_positions = sorted(
        position
        for position, candidate in endpoint_fits.items()
        if (candidate.loss - best_loss) / effective_support
        <= policy.profile_loss_cutoff + loss_tolerance
    )
    clusters: list[list[int]] = []
    for position in plausible_positions:
        if not clusters or position != clusters[-1][-1] + 1:
            clusters.append([position])
        else:
            clusters[-1].append(position)
    if len(clusters) != 1:
        return TroughRefinementResult(
            **{
                **_empty_result("unresolved", "disjoint_modes", policy).__dict__,
                "boundary_candidates": tuple(
                    pd.Timestamp(span.index[position])
                    for position in plausible_positions
                ),
                "local_scale_pp": scale,
                "best_loss": best_loss,
                "effective_support": effective_support,
            }
        )

    final_cluster = clusters[0]
    boundary_position = final_cluster[-1]
    boundary = pd.Timestamp(span.index[boundary_position])
    boundary_fit = endpoint_fits[boundary_position]
    boundary_candidates = tuple(
        pd.Timestamp(span.index[position]) for position in final_cluster
    )
    candidate_span = _month_span(boundary_candidates[0], boundary_candidates[-1])
    if candidate_span > TIMING_IDENTIFIABILITY_DEFAULTS.max_broad_interval_months:
        status: RefinementStatus = "unresolved"
        reason = "boundary_set_too_broad"
        operational_boundary = None
        recovery_start = None
    else:
        provisional_peak = (
            left_peak.timing_status != "point"
            or right_peak.timing_status != "point"
            or left_peak.quality != "normal"
            or right_peak.quality != "normal"
        )
        status = "provisional" if provisional_peak else "confirmed"
        reason = "low_quality_or_interval_peak" if provisional_peak else "accepted"
        operational_boundary = boundary
        recovery_start = boundary + pd.DateOffset(months=1)

    return TroughRefinementResult(
        status=status,
        reason=reason,
        boundary=operational_boundary,
        boundary_candidates=boundary_candidates,
        low_state_start=pd.Timestamp(span.index[boundary_fit.start_position]),
        low_state_end=boundary,
        recovery_start=recovery_start,
        pulse_months=(),
        local_scale_pp=scale,
        best_loss=best_loss,
        effective_support=effective_support,
        policy_version=policy.version,
    )
