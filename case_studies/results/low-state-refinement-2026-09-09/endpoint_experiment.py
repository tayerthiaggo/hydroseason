"""Research-only endpoint experiment. Not imported by HydroSeason production."""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import hydroseason._trough_refinement as core  # noqa: E402

_ORIGINAL_SELECTED_SPAN = core._refine_selected_span
VERSION = "experiment_low_state_projection_v1"


def second_difference_scale(values):
    """Detrended variability under an independent-error, local-linear model.

    For errors of variance sigma**2, (1, -2, 1) has variance 6*sigma**2.
    Curvature changes and temporal dependence can violate this interpretation.
    Finite second differences require three consecutive observed months.
    """
    differences = np.diff(np.asarray(values, dtype=float), n=2)
    differences = differences[np.isfinite(differences)]
    return 1.4826 * core._median_absolute_deviation(differences) / np.sqrt(6.0)


def _project_selected(frame, *, left_peak, right_peak, policy,
                      measurement_tolerance_pp, low_state_z):
    original = _ORIGINAL_SELECTED_SPAN(
        frame, left_peak=left_peak, right_peak=right_peak, policy=policy,
        measurement_tolerance_pp=measurement_tolerance_pp,
    )
    if right_peak is None or left_peak.selected is None or right_peak.selected is None:
        return original
    if original.status in {"unavailable", "awaiting_next_peak"}:
        return original
    if original.status == "unresolved" and original.reason != "boundary_set_too_broad":
        return original
    span = frame.reindex(pd.date_range(left_peak.selected, right_peak.selected, freq="MS"))
    values = span.extent_pct.to_numpy(dtype=float)
    weights = core._support_weights(span)
    # The gap path is retained as the existing conservative result. This first
    # experiment does not claim a new endpoint functional across missing data.
    if len(span) < 3 or not np.isfinite(values).all() or not (weights > 0).all():
        return original
    scale = original.local_scale_pp
    fits = [
        core._fit_valley_huber(values, weights, start, end, scale=scale, huber_k=policy.huber_k)
        for start in range(1, len(span) - 1)
        for end in range(start, len(span) - 1)
    ]
    positions = {span.index.get_loc(date) for date in original.boundary_candidates}
    fits = [fit for fit in fits if fit.converged and fit.end_position in positions]
    if not fits:
        return original
    best = min(fits, key=lambda fit: (fit.loss, -fit.end_position, fit.start_position))
    loss_tolerance = max(np.finfo(float).eps, core._RELATIVE_CONVERGENCE * max(1.0, abs(best.loss)))
    plausible = [
        fit for fit in fits
        if fit.loss - best.loss <= loss_tolerance + (
            policy.profile_loss_cutoff * weights.sum() if scale > 0 else 0.0
        )
    ]
    # One reference for this scenario. Do not reset the level for successive
    # months or different candidate shapes.
    level = float(np.min(best.fitted))
    ceiling = level + low_state_z * scale
    numerical_tolerance = 64 * np.finfo(float).eps * max(float(np.max(np.abs(values))), abs(ceiling), np.finfo(float).tiny)

    def projection(fit):
        low = np.flatnonzero(fit.fitted <= ceiling + numerical_tolerance)
        if not len(low) or low[0] == 0 or low[-1] == len(span) - 1:
            return None
        return int(low[0]), int(low[-1])

    projected = [projection(fit) for fit in plausible]
    nominal = projection(best)
    if nominal is None or any(item is None for item in projected):
        return replace(original, status="unresolved", reason="experimental_no_supported_departure",
                       boundary=None, recovery_start=None, boundary_candidates=())
    endpoints = sorted({item[1] for item in projected})
    if any(right - left != 1 for left, right in zip(endpoints, endpoints[1:])):
        return replace(original, status="unresolved", reason="experimental_disjoint_departures",
                       boundary=None, recovery_start=None,
                       boundary_candidates=tuple(span.index[endpoints]))
    if endpoints[-1] - endpoints[0] > core.TIMING_IDENTIFIABILITY_DEFAULTS.max_broad_interval_months:
        return replace(original, status="unresolved", reason="boundary_set_too_broad",
                       boundary=None, recovery_start=None,
                       boundary_candidates=tuple(span.index[endpoints]))
    start, end = nominal
    status, reason = "confirmed", "accepted"
    if left_peak.quality != "normal" or right_peak.quality != "normal":
        status, reason = "provisional", "low_quality_peak"
    elif left_peak.timing_status != "point" or right_peak.timing_status != "point":
        status, reason = "provisional", "interval_peak"
    elif span.iloc[end + 1:].quality_state.isin(["low", "unknown"]).any():
        status, reason = "provisional", "essential_low_quality_recovery"
    elif span.quality_state.eq("unknown").any():
        status, reason = "provisional", "unknown_quality"
    state_fit = replace(best, start_position=start, end_position=end)
    return replace(
        original, status=status, reason=reason, boundary=span.index[end],
        boundary_candidates=tuple(span.index[endpoints]),
        low_state_start=span.index[start], low_state_end=span.index[end],
        recovery_start=span.index[end + 1],
        pulse_months=core._pulse_dates(span, values, state_fit, scale=scale, policy=policy),
    )


def refine_experimental(frame, *, left_peak, right_peak, policy,
                        measurement_tolerance_pp=0.0, low_state_z=1.0,
                        scale_mode="residual"):
    """Single-thread research hook; reuse the full production sensitivity suite.

    Only the selected-span challenger is replaced temporarily in this process.
    The production source, defaults and on-disk fingerprints never change.
    All peak and quality scenarios call this experimental challenger. No result
    from this function is an accepted production HY boundary.
    """
    if not np.isfinite(low_state_z) or low_state_z < 0:
        raise ValueError("low_state_z must be finite and non-negative")
    if scale_mode != "residual":
        if scale_mode != "second_difference":
            raise ValueError("unsupported experimental scale mode")
    if core._refine_selected_span is not _ORIGINAL_SELECTED_SPAN:
        raise RuntimeError("experiment requires a single-thread, unnested call")

    def selected(frame, **kwargs):
        left = kwargs["left_peak"].selected
        right = kwargs["right_peak"].selected if kwargs["right_peak"] is not None else None
        if scale_mode == "second_difference" and left is not None and right is not None and left < right:
            span = frame.reindex(pd.date_range(left, right, freq="MS"))
            values = span.extent_pct.where(span.quality_state.eq("usable")).to_numpy(dtype=float)
            kwargs["measurement_tolerance_pp"] = max(
                kwargs["measurement_tolerance_pp"], second_difference_scale(values),
            )
        return _project_selected(frame, **kwargs, low_state_z=low_state_z)

    core._refine_selected_span = selected
    try:
        return core.refine_trough_span(
            frame, left_peak=left_peak, right_peak=right_peak,
            policy=replace(policy, version=VERSION),
            measurement_tolerance_pp=measurement_tolerance_pp,
        )
    finally:
        core._refine_selected_span = _ORIGINAL_SELECTED_SPAN
