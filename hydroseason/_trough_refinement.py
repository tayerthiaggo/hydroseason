from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
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
    """Fit one fixed low-state block under squared loss.

    Each unconstrained branch is isotonic before it is clamped to the shared
    low-state level. Between its fitted branch values, the objective is a
    quadratic whose minimiser is the weighted mean of the active observations.
    Evaluating those finite breakpoint regimes is exact and avoids a nested
    numerical search for every candidate block.
    """
    branch = np.full(values.size, np.nan, dtype=float)
    if start:
        branch[:start] = _weighted_pava(
            values[:start][::-1],
            weights[:start][::-1],
            increasing=True,
        )[::-1]
    if end + 1 < values.size:
        branch[end + 1:] = _weighted_pava(
            values[end + 1:],
            weights[end + 1:],
            increasing=True,
        )

    active_weight = float(np.sum(weights[start:end + 1]))
    active_sum = float(np.sum(weights[start:end + 1] * values[start:end + 1]))
    branch_positions = np.flatnonzero(np.isfinite(branch))
    breakpoints = sorted({float(branch[position]) for position in branch_positions})
    regimes: list[tuple[float, float]] = []
    lower = -np.inf
    for upper in (*breakpoints, np.inf):
        mean = active_sum / active_weight
        regimes.append((max(lower, min(mean, upper)), active_weight))
        if not np.isfinite(upper):
            break
        entering = branch_positions[branch[branch_positions] == upper]
        active_weight += float(np.sum(weights[entering]))
        active_sum += float(np.sum(weights[entering] * values[entering]))
        lower = upper

    best_loss = np.inf
    best_fitted = np.empty(values.size, dtype=float)
    for level, _active_weight in regimes:
        fitted = np.where(np.isfinite(branch), np.maximum(branch, level), level)
        loss = float(np.sum(weights * np.square(values - fitted)))
        if loss < best_loss:
            best_loss = loss
            best_fitted = fitted
    return best_fitted


def _fit_valley_l1(
    values: np.ndarray,
    weights: np.ndarray,
    start: int,
    end: int,
) -> _CandidateFit:
    fitted_values, loss = _fit_valley_convex_cached(
        tuple(float(value) for value in values),
        tuple(float(weight) for weight in weights),
        start,
        end,
        0.0,
        1.0,
    )
    return _CandidateFit(
        start_position=start,
        end_position=end,
        fitted=np.asarray(fitted_values, dtype=float),
        loss=loss,
        converged=True,
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
    fitted_values, loss = _fit_valley_convex_cached(
        tuple(float(value) for value in values),
        tuple(float(weight) for weight in weights),
        start,
        end,
        float(scale),
        float(huber_k),
    )
    return _CandidateFit(
        start_position=start,
        end_position=end,
        fitted=np.asarray(fitted_values, dtype=float),
        loss=loss,
        converged=True,
    )


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    order = np.argsort(values, kind="stable")
    ordered_values = values[order]
    cumulative = np.cumsum(weights[order])
    midpoint = float(cumulative[-1]) / 2.0
    position = int(np.searchsorted(cumulative, midpoint, side="left"))
    if (
        position + 1 < len(ordered_values)
        and cumulative[position] == midpoint
    ):
        return float((ordered_values[position] + ordered_values[position + 1]) / 2.0)
    return float(ordered_values[position])


def _robust_location(
    values: np.ndarray,
    weights: np.ndarray,
    *,
    scale: float,
    huber_k: float,
) -> float:
    if scale == 0.0:
        return _weighted_median(values, weights)
    lower = float(np.min(values))
    upper = float(np.max(values))
    if lower == upper:
        return lower
    radius = scale * huber_k
    breakpoints = sorted(
        {float(value - radius) for value in values}
        | {float(value + radius) for value in values}
    )
    tolerance = np.finfo(float).eps * max(1.0, abs(lower), abs(upper), radius)
    for interval_start, interval_end in zip(
        breakpoints, breakpoints[1:], strict=False
    ):
        midpoint = (interval_start + interval_end) / 2.0
        below = values < midpoint - radius
        above = values > midpoint + radius
        active = ~(below | above)
        active_weight = float(np.sum(weights[active]))
        if active_weight == 0.0:
            continue
        root = (
            float(np.sum(weights[active] * values[active]))
            + scale
            * huber_k
            * (float(np.sum(weights[above])) - float(np.sum(weights[below])))
        ) / active_weight
        if interval_start - tolerance <= root <= interval_end + tolerance:
            return max(interval_start, min(root, interval_end))

    # A root may lie exactly on a breakpoint where the adjacent active sets
    # change. Choose the breakpoint with the smallest score deterministically.
    return min(
        breakpoints,
        key=lambda point: abs(
            float(
                np.sum(
                    weights
                    * np.clip((point - values) / scale, -huber_k, huber_k)
                )
            )
        ),
    )


def _robust_isotonic(
    values: np.ndarray,
    weights: np.ndarray,
    *,
    scale: float,
    huber_k: float,
) -> np.ndarray:
    """Generalised PAVA for a separable weighted L1/Huber objective."""
    blocks: list[tuple[list[int], float]] = []
    for position in range(len(values)):
        blocks.append(([position], float(values[position])))
        while len(blocks) >= 2 and blocks[-2][1] > blocks[-1][1]:
            positions = blocks[-2][0] + blocks[-1][0]
            index = np.asarray(positions, dtype=int)
            location = _robust_location(
                values[index],
                weights[index],
                scale=scale,
                huber_k=huber_k,
            )
            blocks[-2:] = [(positions, location)]
    fitted = np.empty(len(values), dtype=float)
    for positions, location in blocks:
        fitted[positions] = location
    return fitted


def _convex_loss(
    values: np.ndarray,
    fitted: np.ndarray,
    weights: np.ndarray,
    *,
    scale: float,
    huber_k: float,
) -> float:
    residual = values - fitted
    if scale == 0.0:
        return float(np.sum(weights * np.abs(residual)))
    magnitude = np.abs(residual / scale)
    losses = np.where(
        magnitude <= huber_k,
        0.5 * np.square(magnitude),
        huber_k * magnitude - 0.5 * huber_k**2,
    )
    return float(np.sum(weights * losses))


def _fit_valley_convex(
    values: np.ndarray,
    weights: np.ndarray,
    start: int,
    end: int,
    *,
    scale: float,
    huber_k: float,
) -> tuple[np.ndarray, float]:
    """Solve a fixed-block valley under weighted L1 or Huber loss."""
    branch = np.full(values.size, np.nan, dtype=float)
    if start:
        branch[:start] = _robust_isotonic(
            values[:start][::-1],
            weights[:start][::-1],
            scale=scale,
            huber_k=huber_k,
        )[::-1]
    if end + 1 < values.size:
        branch[end + 1:] = _robust_isotonic(
            values[end + 1:],
            weights[end + 1:],
            scale=scale,
            huber_k=huber_k,
        )

    active = np.zeros(values.size, dtype=bool)
    active[start:end + 1] = True
    branch_positions = np.flatnonzero(np.isfinite(branch))
    breakpoints = sorted({float(branch[position]) for position in branch_positions})
    levels: list[float] = []
    lower = -np.inf
    for upper in (*breakpoints, np.inf):
        location = _robust_location(
            values[active],
            weights[active],
            scale=scale,
            huber_k=huber_k,
        )
        levels.append(max(lower, min(location, upper)))
        if not np.isfinite(upper):
            break
        active |= np.isfinite(branch) & (branch == upper)
        lower = upper

    best_loss = np.inf
    best_fitted = np.empty(values.size, dtype=float)
    for level in levels:
        fitted = np.where(np.isfinite(branch), np.maximum(branch, level), level)
        loss = _convex_loss(
            values,
            fitted,
            weights,
            scale=scale,
            huber_k=huber_k,
        )
        if loss < best_loss:
            best_loss = loss
            best_fitted = fitted
    return best_fitted, best_loss


@lru_cache(maxsize=8192)
def _fit_valley_convex_cached(
    values: tuple[float, ...],
    weights: tuple[float, ...],
    start: int,
    end: int,
    scale: float,
    huber_k: float,
) -> tuple[tuple[float, ...], float]:
    fitted, loss = _fit_valley_convex(
        np.asarray(values, dtype=float),
        np.asarray(weights, dtype=float),
        start,
        end,
        scale=scale,
        huber_k=huber_k,
    )
    return tuple(float(value) for value in fitted), loss


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
    residuals = values - preliminary.fitted
    residual_scale = 1.4826 * _median_absolute_deviation(residuals)
    if residual_scale > 0.0:
        return residual_scale
    difference_scale = (
        1.4826
        * _median_absolute_deviation(np.diff(residuals))
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


def _huber_value(standardized: float, huber_k: float) -> float:
    magnitude = abs(standardized)
    if magnitude <= huber_k:
        return 0.5 * magnitude**2
    return huber_k * magnitude - 0.5 * huber_k**2


def _pulse_dates(
    span: pd.DataFrame,
    values: np.ndarray,
    fit: _CandidateFit,
    *,
    scale: float,
    policy: TroughRefinementPolicy,
) -> tuple[pd.Timestamp, ...]:
    boundary = fit.end_position
    low_level = float(fit.fitted[boundary])
    tolerance = max(
        np.finfo(float).eps,
        policy.pulse_z * scale,
    )
    pulses: list[pd.Timestamp] = []
    for position in range(1, boundary):
        residual = float(values[position] - fit.fitted[position])
        if residual <= tolerance:
            continue
        if not (
            values[position] > values[position - 1]
            and values[position] >= values[position + 1]
        ):
            continue
        returned = bool(
            np.any(values[position + 1:boundary + 1] <= low_level + tolerance)
        )
        if returned:
            pulses.append(pd.Timestamp(span.index[position]))
    return tuple(pulses)


def _separated_clusters_are_pulses(
    values: np.ndarray,
    endpoint_fits: dict[int, _CandidateFit],
    clusters: list[list[int]],
    *,
    scale: float,
    policy: TroughRefinementPolicy,
) -> bool:
    tolerance = max(np.finfo(float).eps, policy.pulse_z * scale)
    for earlier, later in zip(clusters, clusters[1:]):
        earlier_end = earlier[-1]
        later_start = later[0]
        between = values[earlier_end + 1:later_start]
        if between.size == 0:
            return False
        earlier_level = float(endpoint_fits[earlier_end].fitted[earlier_end])
        later_level = float(endpoint_fits[later_start].fitted[later_start])
        low_ceiling = max(earlier_level, later_level) + tolerance
        returned = values[later_start] <= low_ceiling
        excursion = float(np.max(between)) > low_ceiling
        if not returned or not excursion:
            return False
    return True


def _refine_gap_after_low_state(
    span: pd.DataFrame,
    values_series: pd.Series,
    weights: np.ndarray,
    observed: np.ndarray,
    *,
    policy: TroughRefinementPolicy,
) -> TroughRefinementResult:
    missing = np.flatnonzero(~observed)
    groups = np.split(missing, np.flatnonzero(np.diff(missing) != 1) + 1)
    if len(groups) != 1:
        return _empty_result("unresolved", "gap_overlaps_low_state", policy)
    gap = groups[0]
    gap_start = int(gap[0])
    gap_end = int(gap[-1])
    if gap_start <= 1 or gap_end >= len(span) - 1:
        return _empty_result("unresolved", "gap_overlaps_low_state", policy)
    if not bool(observed[:gap_start].all()) or not bool(observed[gap_end + 1:].all()):
        return _empty_result("unresolved", "gap_overlaps_low_state", policy)

    before = span.iloc[:gap_start]
    before_values = values_series.iloc[:gap_start].to_numpy(dtype=float)
    before_weights = weights[:gap_start]
    last = len(before) - 1
    if last < 1:
        return _empty_result("unresolved", "no_defensible_low_state", policy)

    preliminary = [
        _fit_valley_l1(before_values, before_weights, start, last)
        for start in range(1, last + 1)
    ]
    preliminary = [candidate for candidate in preliminary if candidate.converged]
    if not preliminary:
        return _empty_result("unresolved", "no_converged_candidate", policy)
    preliminary_best = min(
        preliminary,
        key=lambda candidate: (candidate.loss, candidate.start_position),
    )
    scale = _local_scale(before_values, preliminary_best, before)
    candidates = [
        _fit_valley_huber(
            before_values,
            before_weights,
            start,
            last,
            scale=scale,
            huber_k=policy.huber_k,
        )
        for start in range(1, last + 1)
    ]
    candidates = [candidate for candidate in candidates if candidate.converged]
    if not candidates:
        return _empty_result("unresolved", "no_converged_candidate", policy)
    best_loss = min(candidate.loss for candidate in candidates)
    loss_tolerance = max(
        np.finfo(float).eps,
        _RELATIVE_CONVERGENCE * max(1.0, abs(best_loss)),
    )
    best = min(
        (
            candidate
            for candidate in candidates
            if candidate.loss <= best_loss + loss_tolerance
        ),
        key=lambda candidate: candidate.start_position,
    )

    post_value = float(values_series.iloc[gap_end + 1])
    low_level = float(best.fitted[last])
    if scale == 0.0:
        post_low_loss = 0.0 if post_value == low_level else float("inf")
    else:
        post_low_loss = _huber_value(
            (post_value - low_level) / scale,
            policy.huber_k,
        )
    if post_low_loss <= policy.profile_loss_cutoff + loss_tolerance:
        return TroughRefinementResult(
            status="unresolved",
            reason="gap_overlaps_low_state",
            boundary=None,
            boundary_candidates=tuple(
                pd.Timestamp(date) for date in before.index[best.start_position:]
            ),
            low_state_start=pd.Timestamp(before.index[best.start_position]),
            low_state_end=pd.Timestamp(before.index[last]),
            recovery_start=None,
            pulse_months=(),
            local_scale_pp=scale,
            best_loss=best_loss,
            effective_support=float(np.sum(before_weights)),
            policy_version=policy.version,
        )

    boundary = pd.Timestamp(before.index[last])
    return TroughRefinementResult(
        status="provisional",
        reason="recovery_crosses_gap",
        boundary=boundary,
        boundary_candidates=tuple(
            pd.Timestamp(date) for date in before.index[best.start_position:]
        ),
        low_state_start=pd.Timestamp(before.index[best.start_position]),
        low_state_end=boundary,
        recovery_start=None,
        pulse_months=(),
        local_scale_pp=scale,
        best_loss=best_loss,
        effective_support=float(np.sum(before_weights)),
        policy_version=policy.version,
    )


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


def _refine_selected_span(
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
        return _refine_gap_after_low_state(
            span,
            values_series,
            weights,
            observed,
            policy=policy,
        )

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
    if len(clusters) != 1 and not _separated_clusters_are_pulses(
        values,
        endpoint_fits,
        clusters,
        scale=scale,
        policy=policy,
    ):
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

    final_cluster = clusters[-1]
    cluster_best_loss = min(endpoint_fits[position].loss for position in final_cluster)
    # Inside the selected final cluster, a later merely near-equivalent endpoint
    # is already on the best shape's recovery limb. Cap that cluster at its
    # latest exact optimum (Fitzroy Dec -> Jan -> Feb), but do not discard a
    # later separated cluster reached after an observed pulse returns to low.
    departure_position = max(
        position
        for position in final_cluster
        if endpoint_fits[position].loss <= cluster_best_loss + loss_tolerance
    )
    final_cluster = [
        position for position in final_cluster if position <= departure_position
    ]
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
        peak_low_quality = (
            left_peak.quality != "normal" or right_peak.quality != "normal"
        )
        peak_interval = (
            left_peak.timing_status != "point"
            or right_peak.timing_status != "point"
        )
        recovery_quality = span.iloc[boundary_position + 1:]["quality_state"]
        essential_low_quality = recovery_quality.isin(["low", "unknown"]).any()
        unknown_quality = span["quality_state"].eq("unknown").any()
        if peak_low_quality:
            status = "provisional"
            reason = "low_quality_peak"
        elif peak_interval:
            status = "provisional"
            reason = "interval_peak"
        elif essential_low_quality:
            status = "provisional"
            reason = "essential_low_quality_recovery"
        elif unknown_quality:
            status = "provisional"
            reason = "unknown_quality"
        else:
            status = "confirmed"
            reason = "accepted"
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
        pulse_months=_pulse_dates(
            span,
            values,
            boundary_fit,
            scale=scale,
            policy=policy,
        ),
        local_scale_pp=scale,
        best_loss=best_loss,
        effective_support=effective_support,
        policy_version=policy.version,
    )


def _peak_candidate_dates(peak: PeakBoundary) -> tuple[pd.Timestamp, ...]:
    if peak.selected is None:
        return ()
    if peak.timing_status == "point":
        return (pd.Timestamp(peak.selected),)
    dates = {pd.Timestamp(date) for date in peak.candidates}
    dates.add(pd.Timestamp(peak.selected))
    return tuple(sorted(dates))


def _unstable_peak_result(
    nominal: TroughRefinementResult,
) -> TroughRefinementResult:
    return replace(
        nominal,
        status="unresolved",
        reason="unstable_peak_sensitivity",
        boundary=None,
        recovery_start=None,
    )


def _combine_sensitivity_results(
    nominal: TroughRefinementResult,
    scenarios: list[TroughRefinementResult],
    *,
    unstable_reason: str,
) -> TroughRefinementResult:
    if any(
        result.boundary is None
        or result.status not in {"confirmed", "provisional"}
        for result in scenarios
    ):
        return replace(
            nominal,
            status="unresolved",
            reason=unstable_reason,
            boundary=None,
            recovery_start=None,
        )
    candidate_sets = [set(result.boundary_candidates) for result in scenarios]
    shared = set.intersection(*candidate_sets)
    combined = sorted(set.union(*candidate_sets))
    stable = (
        bool(shared)
        and bool(combined)
        and _month_span(combined[0], combined[-1])
        <= TIMING_IDENTIFIABILITY_DEFAULTS.max_broad_interval_months
        and all(
            _month_span(left, right) == 1
            for left, right in zip(combined, combined[1:])
        )
    )
    if not stable:
        return replace(
            nominal,
            status="unresolved",
            reason=unstable_reason,
            boundary=None,
            recovery_start=None,
        )
    selected = max(scenarios, key=lambda result: pd.Timestamp(result.boundary))
    return replace(
        selected,
        boundary=combined[-1],
        boundary_candidates=tuple(combined),
        recovery_start=(
            combined[-1] + pd.DateOffset(months=1)
            if all(result.recovery_start is not None for result in scenarios)
            else None
        ),
        pulse_months=tuple(
            sorted(set().union(*(set(result.pulse_months) for result in scenarios)))
        ),
        local_scale_pp=max(result.local_scale_pp for result in scenarios),
        effective_support=min(result.effective_support for result in scenarios),
    )


def _quality_sensitivity(
    frame: pd.DataFrame,
    left_peak: PeakBoundary,
    right_peak: PeakBoundary,
    policy: TroughRefinementPolicy,
    nominal: TroughRefinementResult,
) -> TroughRefinementResult:
    if nominal.boundary is None:
        return nominal
    left_date = pd.Timestamp(left_peak.selected)
    right_date = pd.Timestamp(right_peak.selected)
    span = frame.loc[left_date:right_date]
    if "quality_state" not in span.columns:
        return nominal
    low_dates = list(span.index[span["quality_state"].eq("low")])
    unknown_dates = list(span.index[span["quality_state"].eq("unknown")])
    if not low_dates and not unknown_dates:
        return nominal

    scenario_frames: list[pd.DataFrame] = []
    removable_low = [date for date in low_dates if date not in {left_date, right_date}]
    if removable_low:
        scenario_frames.append(frame.drop(index=removable_low))
        scenario_frames.extend(frame.drop(index=date) for date in removable_low)
    for date in low_dates:
        observed_fraction = float(span.loc[date, "observed_fraction"])
        value = float(span.loc[date, "extent_pct"])
        lower = value * observed_fraction
        upper = lower + 100.0 * (1.0 - observed_fraction)
        for replacement in (lower, upper):
            changed = frame.copy()
            changed.loc[date, "extent_pct"] = replacement
            scenario_frames.append(changed)
    removable_unknown = [
        date for date in unknown_dates if date not in {left_date, right_date}
    ]
    if removable_unknown:
        scenario_frames.append(frame.drop(index=removable_unknown))

    results = [nominal]
    for scenario_frame in scenario_frames:
        results.append(
            _refine_selected_span(
                scenario_frame,
                left_peak=left_peak,
                right_peak=right_peak,
                policy=policy,
            )
        )
    combined = _combine_sensitivity_results(
        nominal,
        results,
        unstable_reason="unstable_quality_sensitivity",
    )
    if combined.status == "unresolved":
        return combined

    recovery_quality = span.loc[
        (span.index > pd.Timestamp(nominal.boundary))
        & (span.index < right_date),
        "quality_state",
    ]
    if recovery_quality.isin(["low", "unknown"]).any():
        return replace(
            combined,
            status="provisional",
            reason="essential_low_quality_recovery",
        )
    if unknown_dates:
        return replace(combined, status="provisional", reason="unknown_quality")
    return combined


def refine_trough_span(
    frame: pd.DataFrame,
    *,
    left_peak: PeakBoundary,
    right_peak: PeakBoundary | None,
    policy: TroughRefinementPolicy,
) -> TroughRefinementResult:
    """Challenge a trough and propagate all identifiable peak-date evidence."""
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

    nominal_left = replace(
        left_peak,
        candidates=(pd.Timestamp(left_peak.selected),),
        timing_status="point",
    )
    nominal_right = replace(
        right_peak,
        candidates=(pd.Timestamp(right_peak.selected),),
        timing_status="point",
    )
    nominal = _refine_selected_span(
        frame,
        left_peak=nominal_left,
        right_peak=nominal_right,
        policy=policy,
    )
    nominal = _quality_sensitivity(
        frame,
        nominal_left,
        nominal_right,
        policy,
        nominal,
    )
    if left_peak.timing_status == "point" and right_peak.timing_status == "point":
        if nominal.status == "unresolved":
            return nominal
        if left_peak.quality != "normal" or right_peak.quality != "normal":
            return replace(nominal, status="provisional", reason="low_quality_peak")
        return nominal

    scenarios: list[TroughRefinementResult] = []
    for left_date in _peak_candidate_dates(left_peak):
        for right_date in _peak_candidate_dates(right_peak):
            if left_date >= right_date:
                return _unstable_peak_result(nominal)
            scenario_left = PeakBoundary(
                selected=left_date,
                candidates=(left_date,),
                timing_status="point",
                quality=left_peak.quality,
            )
            scenario_right = PeakBoundary(
                selected=right_date,
                candidates=(right_date,),
                timing_status="point",
                quality=right_peak.quality,
            )
            result = _refine_selected_span(
                frame,
                left_peak=scenario_left,
                right_peak=scenario_right,
                policy=policy,
            )
            result = _quality_sensitivity(
                frame,
                scenario_left,
                scenario_right,
                policy,
                result,
            )
            if result.boundary is None or result.status not in {"confirmed", "provisional"}:
                return (
                    result
                    if result.reason == "unstable_quality_sensitivity"
                    else _unstable_peak_result(nominal)
                )
            scenarios.append(result)

    if not scenarios:
        return _unstable_peak_result(nominal)
    selected = _combine_sensitivity_results(
        nominal,
        scenarios,
        unstable_reason="unstable_peak_sensitivity",
    )
    if selected.status == "unresolved":
        return selected
    reason = (
        "low_quality_peak"
        if left_peak.quality != "normal" or right_peak.quality != "normal"
        else "interval_peak"
    )
    return replace(
        selected,
        status="provisional",
        reason=reason,
    )
