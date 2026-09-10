"""Direct-profile low-state-departure challenger (candidate: direct_profile_combined).

Profiles the equivalence-state departure ``T(f, L, delta_pp)`` directly over
a bounded grid of the low-state reference level ``L``, rather than mapping a
finite set of best trough fits through one fixed reference level. Ported
from the Stage B research module
(``case_studies/results/low-state-direct-profile-v2/direct_profile.py``)
after its development/validation gates passed (see that directory's
``findings.md``) and an informal real-catchment spot check (17 disagreement
cases against ``shape_fit``, reviewed by the domain expert; see
``docs/migrations/trough-refinement-candidate.md``).

``refine_selected_span_direct_profile`` matches
``_trough_refinement._refine_selected_span``'s exact calling contract, so
``refine_trough_span``'s dispatcher (keyed on
``TroughRefinementPolicy.candidate``) can route to it for the full peak/
quality sensitivity ensemble -- no monkeypatching, unlike the research
module's ``_with_sensitivity`` wrapper, which this replaces.

Still opt-in and unpromoted: see ``TroughRefinementPolicy.candidate``'s
docstring and the migration doc for what "opt-in" gates concretely.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

import numpy as np
import pandas as pd

from ._trough_refinement import (
    PeakBoundary,
    TroughRefinementPolicy,
    TroughRefinementResult,
    _empty_result,
    _fit_valley_huber,
    _fit_valley_l1,
    _local_scale,
    _measurement_floor,
    _median_absolute_deviation,
    _pulse_dates,
    _RELATIVE_CONVERGENCE,
    _robust_isotonic,
    _support_weights,
)


def l_grid(
    block_level: float,
    scale: float,
    *,
    l_uncertainty_k: float,
    n_steps_per_scale: int = 4,
) -> np.ndarray:
    """Symmetric grid of admissible ``L`` values around ``block_level``.

    ``scale == 0.0`` means there is no positive floor to bound an
    uncertainty region around, so the grid collapses to the single point
    estimate.
    """
    if scale == 0.0:
        return np.array([block_level], dtype=float)
    n_l = int(round(l_uncertainty_k * n_steps_per_scale))
    step = scale / n_steps_per_scale
    offsets = np.arange(-n_l, n_l + 1, dtype=float) * step
    return block_level + offsets


@dataclass(frozen=True)
class _DirectProfileFit:
    start_position: int
    end_position: int
    reference_level: float
    fitted: np.ndarray
    loss: float


def _huber_loss(residual: np.ndarray, weights: np.ndarray, *, scale: float, huber_k: float) -> float:
    if scale == 0.0:
        return float(np.sum(weights * np.abs(residual)))
    magnitude = np.abs(residual / scale)
    losses = np.where(
        magnitude <= huber_k,
        0.5 * np.square(magnitude),
        huber_k * magnitude - 0.5 * huber_k**2,
    )
    return float(np.sum(weights * losses))


def fit_with_reference_level(
    values: np.ndarray,
    weights: np.ndarray,
    start: int,
    end: int,
    *,
    level: float,
    scale: float,
    huber_k: float,
) -> _DirectProfileFit:
    """Clamp the low-state block to ``level`` exactly; branches stay isotonic."""
    branch = np.full(values.size, np.nan, dtype=float)
    if start:
        branch[:start] = _robust_isotonic(
            values[:start][::-1], weights[:start][::-1], scale=scale, huber_k=huber_k,
        )[::-1]
    if end + 1 < values.size:
        branch[end + 1:] = _robust_isotonic(
            values[end + 1:], weights[end + 1:], scale=scale, huber_k=huber_k,
        )
    fitted = np.where(np.isfinite(branch), np.maximum(branch, level), level)
    loss = _huber_loss(values - fitted, weights, scale=scale, huber_k=huber_k)
    return _DirectProfileFit(
        start_position=start, end_position=end, reference_level=level, fitted=fitted, loss=loss,
    )


def final_departure_index(
    fitted: np.ndarray,
    *,
    level: float,
    delta_pp: float,
    tolerance: float,
) -> int | None:
    """``T(f, L, delta)``: last interior index inside the equivalence ceiling.

    Interior means excluding both span edges (index 0 and ``len - 1``). If
    the contiguous low run touching the candidate index reaches either edge,
    "final departure" is undefined for this fit and ``None`` is returned.
    """
    n = fitted.size
    ceiling = level + delta_pp + tolerance
    below = np.flatnonzero(fitted <= ceiling)
    interior = below[(below > 0) & (below < n - 1)]
    if interior.size == 0:
        return None
    candidate = int(interior[-1])
    run_start = candidate
    while run_start - 1 >= 0 and fitted[run_start - 1] <= ceiling:
        run_start -= 1
    run_end = candidate
    while run_end + 1 < n and fitted[run_end + 1] <= ceiling:
        run_end += 1
    if run_start == 0 or run_end == n - 1:
        return None
    return candidate


def _second_difference_scale(values: np.ndarray) -> float:
    """Detrended variability estimate (numerics spec section 6, Stage 2).

    Requires at least 3 consecutive finite second differences (4 consecutive
    usable months); returns 0.0 otherwise, so the domain-restricted combined
    estimator below falls back to the residual-only estimator.
    """
    differences = np.diff(values, n=2)
    differences = differences[np.isfinite(differences)]
    if differences.size < 3:
        return 0.0
    return 1.4826 * _median_absolute_deviation(differences) / np.sqrt(6.0)


def _combined_scale(
    values: np.ndarray,
    residual_scale: float,
    frame: pd.DataFrame,
    *,
    measurement_tolerance_pp: float,
) -> float:
    """Stage 2 automatic-scale hypothesis: max of residual, second-difference
    (only within its stated domain of applicability), measurement floor, and
    the caller's declared tolerance."""
    candidates = [residual_scale, _measurement_floor(frame), measurement_tolerance_pp]
    second_difference = _second_difference_scale(values)
    if second_difference > 0.0:
        candidates.append(second_difference)
    return max(candidates)


def _natural_reference_level(
    values: np.ndarray, weights: np.ndarray, *, scale: float, huber_k: float,
) -> float:
    """Single global low-state reference ``L0``: the block level of the
    best-fitting unconstrained valley shape (today's production search,
    ``_fit_valley_huber`` over every ``(start, end)``). Shared across every
    ``(start, end, L)`` combination the profile evaluates, per the endpoint
    contract's common-reference rule: the reference must not be re-derived
    per candidate block, or a sequence of small increases could chain into
    a drifting low state.
    """
    n = values.size
    best = None
    for start in range(1, n - 1):
        for end in range(start, n - 1):
            fit = _fit_valley_huber(values, weights, start, end, scale=scale, huber_k=huber_k)
            if not fit.converged:
                continue
            if best is None or fit.loss < best.loss:
                best = fit
    if best is None:
        return float(np.median(values))
    return float(np.min(best.fitted))


@dataclass(frozen=True)
class _DirectProfileSolution:
    support_positions: tuple[int, ...]
    departure_position: int | None
    best_loss: float
    reference_level_at_best: float
    scale: float
    loss_basis: Literal["standardized_huber", "exact_l1", "unavailable"]
    start_position_at_best: int | None = None
    fit_at_best: _DirectProfileFit | None = None
    # Fits for every member of the final support cluster (not just the
    # winning departure position), so a caller can re-anchor the reported
    # boundary to an earlier, more reliable cluster member -- e.g. when the
    # naive latest month is too cloud-contaminated to publish as an
    # operational date -- without re-solving the profile from scratch.
    fits_in_final_cluster: dict[int, _DirectProfileFit] | None = None


def solve_direct_profile(
    values: np.ndarray,
    weights: np.ndarray,
    *,
    delta_pp: float,
    scale: float,
    huber_k: float,
    profile_loss_cutoff: float,
    l_uncertainty_k: float,
) -> _DirectProfileSolution:
    """Grid-search ``(start, end)`` against one shared ``L`` grid; profile
    ``Q(d) = T(f, L, delta)`` over the joint (position, reference-level)
    space (numerics spec section 2)."""
    n = values.size
    loss_basis: Literal["standardized_huber", "exact_l1"] = (
        "exact_l1" if scale == 0.0 else "standardized_huber"
    )
    numerical_tolerance = 64 * np.finfo(float).eps * max(
        float(np.max(np.abs(values))), abs(delta_pp), np.finfo(float).tiny,
    )
    effective_support = float(np.sum(weights))

    reference_level = _natural_reference_level(values, weights, scale=scale, huber_k=huber_k)
    grid = l_grid(reference_level, scale, l_uncertainty_k=l_uncertainty_k)

    best_by_departure: dict[int, _DirectProfileFit] = {}
    overall_best_loss = np.inf

    for start in range(1, n - 1):
        for end in range(start, n - 1):
            for level in grid:
                fit = fit_with_reference_level(
                    values, weights, start, end, level=level, scale=scale, huber_k=huber_k,
                )
                if fit.loss < overall_best_loss:
                    overall_best_loss = fit.loss
                departure = final_departure_index(
                    fit.fitted, level=level, delta_pp=delta_pp, tolerance=numerical_tolerance,
                )
                if departure is None:
                    continue
                current = best_by_departure.get(departure)
                if current is None or fit.loss < current.loss:
                    best_by_departure[departure] = fit

    if not best_by_departure:
        return _DirectProfileSolution(
            support_positions=(), departure_position=None,
            best_loss=float(overall_best_loss) if np.isfinite(overall_best_loss) else float("nan"),
            reference_level_at_best=float("nan"), scale=scale, loss_basis=loss_basis,
        )

    # Plausibility is measured against the TRUE global optimum across every
    # (start, end, L) combination -- including combinations whose departure
    # is undefined (a "no departure" / flat-band explanation). A departure
    # candidate is only genuinely supported if it competes with that global
    # optimum, not merely with the best among already-departure-labelled
    # fits (numerics spec section 2.4; see also the flat-series negative
    # control test).
    tolerance = max(np.finfo(float).eps, _RELATIVE_CONVERGENCE * max(1.0, abs(overall_best_loss)))
    if scale == 0.0:
        plausible = sorted(
            position for position, fit in best_by_departure.items()
            if fit.loss <= overall_best_loss + tolerance
        )
    else:
        plausible = sorted(
            position for position, fit in best_by_departure.items()
            if (fit.loss - overall_best_loss) / effective_support <= profile_loss_cutoff + tolerance
        )

    clusters: list[list[int]] = []
    for position in plausible:
        if not clusters or position != clusters[-1][-1] + 1:
            clusters.append([position])
        else:
            clusters[-1].append(position)
    final_cluster = clusters[-1] if clusters else []
    if not final_cluster:
        return _DirectProfileSolution(
            support_positions=(), departure_position=None, best_loss=float(overall_best_loss),
            reference_level_at_best=float("nan"), scale=scale, loss_basis=loss_basis,
        )

    cluster_best_loss = min(best_by_departure[p].loss for p in final_cluster)
    departure_position = max(
        p for p in final_cluster if best_by_departure[p].loss <= cluster_best_loss + tolerance
    )
    winning_fit = best_by_departure[departure_position]
    return _DirectProfileSolution(
        support_positions=tuple(final_cluster),
        departure_position=departure_position,
        best_loss=float(overall_best_loss),
        reference_level_at_best=winning_fit.reference_level,
        scale=scale,
        loss_basis=loss_basis,
        start_position_at_best=winning_fit.start_position,
        fit_at_best=winning_fit,
        fits_in_final_cluster={p: best_by_departure[p] for p in final_cluster},
    )


def _refine_gap_direct_profile(
    span: pd.DataFrame,
    values_series: pd.Series,
    weights: np.ndarray,
    observed: np.ndarray,
    *,
    policy: TroughRefinementPolicy,
    measurement_tolerance_pp: float,
) -> TroughRefinementResult:
    """Pre-gap-only path, re-expressed in terms of the equivalence ceiling.

    Structurally identical to production's ``_refine_gap_after_low_state``
    (gap detection, pre-gap segment feasibility, post-gap compatibility
    checks). The one change is the post-gap comparisons: ``value <= L +
    delta_pp`` (this candidate's target) instead of the raw Huber-loss
    profile cutoff (the shape_fit target's unit).
    """
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
        preliminary, key=lambda candidate: (candidate.loss, candidate.start_position),
    )
    scale = _local_scale(
        before_values, preliminary_best, before, measurement_tolerance_pp=measurement_tolerance_pp,
    )
    candidates = [
        _fit_valley_huber(before_values, before_weights, start, last, scale=scale, huber_k=policy.huber_k)
        for start in range(1, last + 1)
    ]
    candidates = [candidate for candidate in candidates if candidate.converged]
    if not candidates:
        return _empty_result("unresolved", "no_converged_candidate", policy)
    best_loss = min(candidate.loss for candidate in candidates)
    loss_tolerance = max(np.finfo(float).eps, _RELATIVE_CONVERGENCE * max(1.0, abs(best_loss)))
    best = min(
        (candidate for candidate in candidates if candidate.loss <= best_loss + loss_tolerance),
        key=lambda candidate: candidate.start_position,
    )

    low_level = float(best.fitted[last])
    loss_basis: Literal["standardized_huber", "exact_l1"] = (
        "exact_l1" if scale == 0.0 else "standardized_huber"
    )
    ceiling = low_level + policy.delta_pp
    numerical_tolerance = 64 * np.finfo(float).eps * max(abs(ceiling), 1.0)

    after_values = values_series.iloc[gap_end + 1:].to_numpy(dtype=float)
    low_state_continues_past_gap = bool(np.any(after_values < low_level - numerical_tolerance))
    if low_state_continues_past_gap:
        return _empty_result("unresolved", "gap_before_low_state", policy)

    at_low_level = after_values <= ceiling + numerical_tolerance
    if bool(at_low_level[0]):
        return TroughRefinementResult(
            status="unresolved", reason="gap_overlaps_low_state", boundary=None,
            boundary_candidates=tuple(pd.Timestamp(date) for date in before.index[best.start_position:]),
            low_state_start=pd.Timestamp(before.index[best.start_position]),
            low_state_end=pd.Timestamp(before.index[last]), recovery_start=None, pulse_months=(),
            local_scale_pp=scale, best_loss=best_loss, effective_support=float(np.sum(before_weights)),
            policy_version=policy.version, loss_basis=loss_basis,
        )
    if bool(np.any(at_low_level[1:])):
        return TroughRefinementResult(
            status="unresolved", reason="post_gap_return_to_low_state", boundary=None,
            boundary_candidates=tuple(pd.Timestamp(date) for date in before.index[best.start_position:]),
            low_state_start=pd.Timestamp(before.index[best.start_position]),
            low_state_end=pd.Timestamp(before.index[last]), recovery_start=None, pulse_months=(),
            local_scale_pp=scale, best_loss=best_loss, effective_support=float(np.sum(before_weights)),
            policy_version=policy.version, loss_basis=loss_basis,
        )

    # Same reliability guard as the main (non-gap) path: `last` is only the
    # latest OBSERVED pre-gap month, not necessarily a reliable one. Without
    # this, a sensitivity-ensemble scenario that happens to mask a later
    # month as the "gap" can smuggle an unreliable month back in as the
    # published boundary even when the main path already excluded it (see
    # the Gilbert River 2010 case: masking January alone reintroduces
    # December, which max()-wins across the ensemble's scenarios).
    #
    # Reliability alone is not enough, though: this function's "before"
    # fit always forces the block to end exactly at `last`, so `low_level`
    # is partly derived from `last`'s own value and can't be used to test
    # it. A real, fully-usable month can still be a spike well outside the
    # low state's own equivalence band (Daly River HY2016/HY2024: December
    # is usable-quality but ~2x the trough level, sitting right before a
    # low-quality January gap) -- the main path's `final_departure_index`
    # would never let such a value pass, but this gap path's fixed-end
    # block bypasses that test entirely. Guard against both failure modes
    # together: walk back from `last` to the latest month that is both
    # quality-reliable and within delta_pp of the segment's own natural
    # (outlier-robust) reference level.
    quality_state = before["quality_state"]
    plausible_level = _natural_reference_level(
        before_values, before_weights, scale=scale, huber_k=policy.huber_k,
    )
    plausibility_ceiling = plausible_level + policy.delta_pp
    plausibility_tolerance = 64 * np.finfo(float).eps * max(abs(plausibility_ceiling), 1.0)
    reliable_position = next(
        (
            position for position in range(last, best.start_position - 1, -1)
            if quality_state.iloc[position] != "low"
            and before_values[position] <= plausibility_ceiling + plausibility_tolerance
        ),
        None,
    )
    if reliable_position is None:
        return TroughRefinementResult(
            status="unresolved", reason="no_reliable_boundary_in_support", boundary=None,
            boundary_candidates=tuple(pd.Timestamp(date) for date in before.index[best.start_position:]),
            low_state_start=None, low_state_end=None, recovery_start=None, pulse_months=(),
            local_scale_pp=scale, best_loss=best_loss, effective_support=float(np.sum(before_weights)),
            policy_version=policy.version, loss_basis=loss_basis,
        )
    boundary = pd.Timestamp(before.index[reliable_position])
    if reliable_position == last:
        reason = "recovery_crosses_gap"
    elif quality_state.iloc[last] == "low":
        reason = "boundary_deferred_to_reliable_month"
    else:
        reason = "boundary_deferred_to_implausible_month"
    return TroughRefinementResult(
        status="provisional", reason=reason, boundary=boundary,
        boundary_candidates=tuple(pd.Timestamp(date) for date in before.index[best.start_position:]),
        low_state_start=pd.Timestamp(before.index[best.start_position]), low_state_end=boundary,
        recovery_start=None, pulse_months=(), local_scale_pp=scale, best_loss=best_loss,
        effective_support=float(np.sum(before_weights)), policy_version=policy.version, loss_basis=loss_basis,
    )


def refine_selected_span_direct_profile(
    frame: pd.DataFrame,
    *,
    left_peak: PeakBoundary,
    right_peak: PeakBoundary | None,
    policy: TroughRefinementPolicy,
    measurement_tolerance_pp: float = 0.0,
) -> TroughRefinementResult:
    """Direct-profile core, matching ``_refine_selected_span``'s exact
    calling contract so ``refine_trough_span``'s dispatcher can route the
    real peak/quality sensitivity ensemble through it (see
    ``TroughRefinementPolicy.candidate``).
    """
    if right_peak is None:
        return _empty_result("awaiting_next_peak", "open_span", policy)
    if (
        left_peak.selected is None
        or right_peak.selected is None
        or left_peak.timing_status == "unresolved"
        or right_peak.timing_status == "unresolved"
    ):
        return _empty_result("unavailable", "missing_or_unresolved_peak", policy)

    left_date = pd.Timestamp(left_peak.selected)
    right_date = pd.Timestamp(right_peak.selected)
    if left_date >= right_date or left_date not in frame.index or right_date not in frame.index:
        return _empty_result("unavailable", "missing_or_unresolved_peak", policy)

    span = frame.reindex(pd.date_range(left_date, right_date, freq="MS")).copy()
    if "quality_state" in span.columns:
        span["quality_state"] = span["quality_state"].fillna("missing")
    if "candidate_usable" in span.columns:
        span["candidate_usable"] = span["candidate_usable"].fillna(False).astype(bool)
    if "observed_fraction" in span.columns:
        span["observed_fraction"] = span["observed_fraction"].fillna(0.0)

    values_series = pd.to_numeric(span["extent_pct"], errors="coerce")
    weights = _support_weights(span)
    observed = values_series.notna().to_numpy() & (weights > 0.0)
    if len(span) < 3 or not bool(observed[0]) or not bool(observed[-1]):
        return _empty_result("unresolved", "no_defensible_low_state", policy)
    if not bool(observed.all()):
        return _refine_gap_direct_profile(
            span, values_series, weights, observed,
            policy=policy, measurement_tolerance_pp=measurement_tolerance_pp,
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
        preliminary, key=lambda candidate: (candidate.loss, candidate.end_position, candidate.start_position),
    )
    residual_scale = _local_scale(
        values, preliminary_best, span, measurement_tolerance_pp=measurement_tolerance_pp,
    )
    if policy.scale_mode == "combined":
        scale = _combined_scale(values, residual_scale, span, measurement_tolerance_pp=measurement_tolerance_pp)
    else:
        scale = residual_scale

    solution = solve_direct_profile(
        values, weights, delta_pp=policy.delta_pp, scale=scale, huber_k=policy.huber_k,
        profile_loss_cutoff=policy.profile_loss_cutoff, l_uncertainty_k=policy.l_uncertainty_k,
    )
    if solution.departure_position is None:
        return TroughRefinementResult(
            status="unresolved", reason="no_defensible_low_state", boundary=None,
            boundary_candidates=(), low_state_start=None, low_state_end=None,
            recovery_start=None, pulse_months=(), local_scale_pp=scale,
            best_loss=solution.best_loss, effective_support=float(np.sum(weights)),
            policy_version=policy.version, loss_basis=solution.loss_basis,
        )

    # The statistically-plausible support cluster can legitimately include a
    # month whose own observation is heavily cloud-contaminated: the profile
    # only sees its value, not its reliability. Never publish an unreliable
    # month as the operational boundary -- a downstream step that pulls the
    # raster/extent layer at the reported date would inherit a mostly-invalid
    # layer. Defer to the latest RELIABLE month at or before the naive
    # departure position (never later -- this only guards which calendar
    # month gets published, not the timing conclusion itself); abstain if no
    # month in the cluster is reliable enough to stand behind.
    quality_state = span["quality_state"]
    reliable_position = next(
        (
            position for position in sorted(
                (p for p in solution.support_positions if p <= solution.departure_position),
                reverse=True,
            )
            if quality_state.iloc[position] != "low"
        ),
        None,
    )
    if reliable_position is None:
        return TroughRefinementResult(
            status="unresolved", reason="no_reliable_boundary_in_support", boundary=None,
            boundary_candidates=tuple(span.index[p] for p in solution.support_positions),
            low_state_start=None, low_state_end=None, recovery_start=None, pulse_months=(),
            local_scale_pp=scale, best_loss=solution.best_loss, effective_support=float(np.sum(weights)),
            policy_version=policy.version, loss_basis=solution.loss_basis,
        )
    boundary_deferred = reliable_position != solution.departure_position
    boundary_position = reliable_position
    boundary_candidates = tuple(span.index[p] for p in solution.support_positions)
    # The (start, end, L) triple already found by the solver's own grid
    # search is the low-state occupancy: re-deriving it from a separate
    # single-level re-fit would ignore the isotonic branch construction that
    # lets the solver's fit absorb a pulse via pooling rather than forcing
    # it into a flat block (see the pulse-return test).
    assert solution.fits_in_final_cluster is not None
    best_fit = solution.fits_in_final_cluster[boundary_position]
    best_start = best_fit.start_position
    boundary = span.index[boundary_position]
    pulse_fit = replace(best_fit, end_position=boundary_position)

    peak_low_quality = left_peak.quality != "normal" or right_peak.quality != "normal"
    peak_interval = left_peak.timing_status != "point" or right_peak.timing_status != "point"
    recovery_quality = span.iloc[boundary_position + 1:]["quality_state"]
    essential_low_quality = recovery_quality.isin(["low", "unknown"]).any()
    unknown_quality = span["quality_state"].eq("unknown").any()
    if peak_low_quality:
        status, reason = "provisional", "low_quality_peak"
    elif peak_interval:
        status, reason = "provisional", "interval_peak"
    elif boundary_deferred:
        status, reason = "provisional", "boundary_deferred_to_reliable_month"
    elif essential_low_quality:
        status, reason = "provisional", "essential_low_quality_recovery"
    elif unknown_quality:
        status, reason = "provisional", "unknown_quality"
    else:
        status, reason = "confirmed", "accepted"

    return TroughRefinementResult(
        status=status, reason=reason, boundary=boundary,
        boundary_candidates=boundary_candidates,
        low_state_start=span.index[best_start], low_state_end=boundary,
        recovery_start=boundary + pd.DateOffset(months=1),
        pulse_months=_pulse_dates(span, values, pulse_fit, scale=scale, policy=policy),
        local_scale_pp=scale, best_loss=solution.best_loss,
        effective_support=float(np.sum(weights)), policy_version=policy.version,
        loss_basis=solution.loss_basis,
    )
